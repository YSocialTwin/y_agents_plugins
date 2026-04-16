from __future__ import annotations

from typing import Any

from sqlalchemy import Column, Integer, MetaData, Table, select

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec, PostRecord, UserRecord
from y_agents_plugins.plugins.base import BaseAgentPlugin


class StressAttackerAgent(BaseAgentPlugin):
    """Synthetic stress-event injector used to exercise mitigation pipelines safely."""

    agent_type = "stress_attacker"
    _SAFETY_DIRECTIVE = (
        "Keep the message critical, antagonistic and personal. "
        "Focus on disagreement, inconsistency, skepticism and mockery using a confronting language."
    )
    _DEFAULT_SYNTHETIC_COMMENT = (
        "Shout up! That's completely nonsense! "
        "You're embarrassing yourself, y'a know!?"
    )

    def setup_database(self, database, connection) -> None:
        super().setup_database(database, connection)
        metadata = MetaData()
        campaign_state = Table(
            "stress_attacker_campaigns",
            metadata,
            Column("attacker_uid", Integer, primary_key=True),
            Column("target_uid", Integer, nullable=True),
            Column("burst_started_round", Integer, nullable=True),
            Column("cooldown_until_round", Integer, nullable=True),
        )
        if not database.has_table(connection, "stress_attacker_campaigns"):
            campaign_state.create(connection, checkfirst=True)
            connection.commit()

    def on_tick(self, context: AgentContext, agent: AgentSpec) -> list[AgentAction]:
        settings = self._resolved_settings(agent)
        if context.connection is None:
            return [self._read_action(context, agent)]

        attacker_uid = self.database.get_user_id(context.connection, agent.username)
        target_user = self._resolve_target(
            context=context,
            attacker_uid=attacker_uid,
            settings=settings,
        )
        if target_user is None:
            return [self._read_action(context, agent)]

        remaining_budget = self._remaining_daily_budget(
            context=context,
            attacker_uid=attacker_uid,
            daily_budget=agent.daily_budget,
        )
        actions: list[AgentAction] = [self._read_action(context, agent)]
        if remaining_budget <= 0:
            return actions

        source_count = max(1, int(settings.get("source_count", 3) or 3))
        recent_posts = self._candidate_posts_for_target(
            context=context,
            target_user_id=int(target_user.id),
            lookback_rounds=max(1, int(settings.get("post_lookback_rounds", 24) or 24)),
        )
        target_post = recent_posts[0] if recent_posts else None

        if self._enabled(settings, "negative_reactions_enabled") and target_post is not None:
            actions.append(
                AgentAction(
                    agent_type=self.agent_type,
                    action_type="APPLY_STRESS_EVENT",
                    payload={
                        "target_user_id": int(target_user.id),
                        "family": "reaction",
                        "subtype": "dislike",
                        "action_name": "synthetic_reaction:dislike_burst",
                        "volume": max(
                            1,
                            int(settings.get("reaction_burst_volume", source_count) or source_count),
                        ),
                        "source_count": source_count,
                        "target_post_id": int(target_post.id),
                    },
                )
            )
            remaining_budget -= 1

        if remaining_budget > 0 and self._enabled(settings, "critical_comment_enabled"):
            surfaced_post = recent_posts[-1] if recent_posts else None
            critical_comment_mode = str(
                settings.get("critical_comment_mode") or "synthetic"
            ).strip().lower()
            if surfaced_post is not None and critical_comment_mode in {"llm", "synthetic"}:
                actions.append(
                    AgentAction(
                        agent_type=self.agent_type,
                        action_type="CREATE_COMMENT",
                        payload={
                            "parent_post_id": int(surfaced_post.id),
                            "thread_id": int(surfaced_post.thread_id or surfaced_post.id),
                            "text": (
                                self._build_critical_comment(
                                    agent=agent,
                                    target_user=target_user,
                                    target_post=surfaced_post,
                                )
                                if critical_comment_mode == "llm"
                                else self._build_synthetic_comment(
                                    agent=agent,
                                    target_user=target_user,
                                )
                            ),
                            "stress_reward": {
                                "tone": "critical",
                                "action": "comment:critical",
                            },
                        },
                    )
                )
            else:
                actions.append(
                    AgentAction(
                        agent_type=self.agent_type,
                        action_type="APPLY_STRESS_EVENT",
                        payload={
                            "target_user_id": int(target_user.id),
                        "family": "comment",
                        "subtype": "critical",
                        "action_name": "synthetic_comment:critical",
                        "source_count": source_count,
                        "source_post_id": (int(surfaced_post.id) if surfaced_post is not None else None),
                    },
                )
            )
            remaining_budget -= 1

        if remaining_budget > 0 and self._enabled(settings, "report_burst_enabled") and target_post is not None:
            report_volume = max(
                1,
                int(settings.get("report_burst_volume", source_count) or source_count),
            )
            actions.append(
                AgentAction(
                    agent_type=self.agent_type,
                    action_type="REPORT_POST",
                    payload={
                        "post_id": int(target_post.id),
                        "target_user_id": int(target_user.id),
                        "report_type": "synthetic_pressure",
                        "source_count": report_volume,
                        "action_name": "report:pressure",
                    },
                )
            )
            actions.append(
                AgentAction(
                    agent_type=self.agent_type,
                    action_type="APPLY_STRESS_EVENT",
                    payload={
                        "target_user_id": int(target_user.id),
                        "family": "report",
                        "subtype": "mass_report",
                        "action_name": "report:pressure",
                        "volume": report_volume,
                        "source_count": report_volume,
                        "target_post_id": int(target_post.id),
                    },
                )
            )
            remaining_budget -= 1

        return actions

    def _resolve_target(
        self,
        *,
        context: AgentContext,
        attacker_uid: int,
        settings: dict[str, Any],
    ) -> UserRecord | None:
        state = self._load_campaign_state(context, attacker_uid=attacker_uid)
        current_round = int(context.current_round.id)
        burst_rounds = max(1, int(settings.get("burst_rounds", 4) or 4))
        if state is not None:
            target_uid = state.get("target_uid")
            burst_started_round = int(state.get("burst_started_round") or 0)
            cooldown_until_round = int(state.get("cooldown_until_round") or 0)
            if target_uid and burst_started_round > 0 and current_round <= burst_started_round + burst_rounds - 1:
                target = self._user_by_id(int(target_uid), users=context.users)
                if target is not None and not self.database.user_is_banned(
                    context.connection, user_id=int(target.id)
                ):
                    return target
            if cooldown_until_round > current_round:
                return None

        target = self._select_target_candidate(
            context=context,
            attacker_uid=attacker_uid,
            settings=settings,
        )
        cooldown_rounds = max(0, int(settings.get("cooldown_rounds", 8) or 8))
        self._store_campaign_state(
            context=context,
            attacker_uid=attacker_uid,
            target_uid=(int(target.id) if target is not None else None),
            burst_started_round=(current_round if target is not None else None),
            cooldown_until_round=(
                current_round + burst_rounds + cooldown_rounds if target is not None else current_round + cooldown_rounds
            ),
        )
        return target

    def _select_target_candidate(
        self,
        *,
        context: AgentContext,
        attacker_uid: int,
        settings: dict[str, Any],
    ) -> UserRecord | None:
        candidates = []
        for user in context.users:
            if int(user.id) == int(attacker_uid):
                continue
            user_type = str(user.user_type or "").strip().lower()
            if user_type in {"stress_attacker", "hello_world", "moderator", "propaganda", "master_of_puppets", "mop_puppet"}:
                continue
            if self.database.user_is_banned(context.connection, user_id=int(user.id)):
                continue
            if not self._matches_demographics(user, settings):
                continue
            recent_posts = self._candidate_posts_for_target(
                context=context,
                target_user_id=int(user.id),
                lookback_rounds=max(1, int(settings.get("post_lookback_rounds", 24) or 24)),
            )
            score = (
                len(recent_posts),
                int(user.profile.get("age") or 0),
                -int(user.id),
            )
            candidates.append((score, user))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def _matches_demographics(self, user: UserRecord, settings: dict[str, Any]) -> bool:
        profile = user.profile or {}
        target_filters = list(settings.get("target_filters") or [])
        if not target_filters:
            target_filters = self._legacy_target_filters(settings)
        interests_value = str(profile.get("interests") or "")
        custom_features = profile.get("custom_features") or {}
        stubborn_topics = profile.get("stubborn_topics") or {}
        for entry in target_filters:
            if not isinstance(entry, dict):
                continue
            feature = str(entry.get("feature") or "").strip()
            value = entry.get("value")
            if not feature:
                continue
            if feature == "user_type":
                if str(user.user_type or "").strip().casefold() != str(value or "").strip().casefold():
                    return False
                continue
            if feature == "leaning":
                if str(profile.get("leaning") or "").strip().casefold() != str(value or "").strip().casefold():
                    return False
                continue
            if feature == "language":
                if str(profile.get("language") or "").strip().casefold() != str(value or "").strip().casefold():
                    return False
                continue
            if feature == "gender":
                if str(profile.get("gender") or "").strip().casefold() != str(value or "").strip().casefold():
                    return False
                continue
            if feature == "nationality":
                if str(profile.get("nationality") or "").strip().casefold() != str(value or "").strip().casefold():
                    return False
                continue
            if feature == "education_level":
                if str(profile.get("education_level") or "").strip().casefold() != str(value or "").strip().casefold():
                    return False
                continue
            if feature == "profession":
                if str(profile.get("profession") or "").strip().casefold() != str(value or "").strip().casefold():
                    return False
                continue
            if feature == "topic":
                normalized_value = str(value or "").strip().casefold()
                if (
                    normalized_value not in interests_value.casefold()
                    and all(str(key).strip().casefold() != normalized_value for key in stubborn_topics.keys())
                    and all(str(key).strip().casefold() != normalized_value for key in custom_features.keys())
                ):
                    return False
                continue
            if feature == "interest_contains":
                if str(value or "").strip().casefold() not in interests_value.casefold():
                    return False
                continue
            if feature == "min_age":
                age = profile.get("age")
                if age in (None, "") or int(age) < int(value):
                    return False
                continue
            if feature == "max_age":
                age = profile.get("age")
                if age in (None, "") or int(age) > int(value):
                    return False
                continue
            if feature.startswith("custom:"):
                key = feature.split(":", 1)[1]
                if str(custom_features.get(key) or "").strip().casefold() != str(value or "").strip().casefold():
                    return False
        return True

    @staticmethod
    def _legacy_target_filters(settings: dict[str, Any]) -> list[dict[str, Any]]:
        filters: list[dict[str, Any]] = []
        requested_types = [
            chunk.strip()
            for chunk in str(settings.get("target_user_types", "") or "").split(",")
            if chunk.strip()
        ]
        for requested_type in requested_types:
            filters.append({"feature": "user_type", "value": requested_type})
        for legacy_key, feature in (
            ("target_leaning", "leaning"),
            ("target_language", "language"),
            ("target_education_level", "education_level"),
            ("target_interest_contains", "interest_contains"),
            ("target_min_age", "min_age"),
            ("target_max_age", "max_age"),
        ):
            value = settings.get(legacy_key)
            if value not in (None, ""):
                filters.append({"feature": feature, "value": value})
        return filters

    def _candidate_posts_for_target(
        self,
        *,
        context: AgentContext,
        target_user_id: int,
        lookback_rounds: int,
    ) -> tuple[PostRecord, ...]:
        min_round_id = max(1, int(context.current_round.id) - max(0, int(lookback_rounds)))
        posts = self.database.get_posts_by_author_ids_since_round(
            context.connection,
            author_ids=[int(target_user_id)],
            min_round_id=min_round_id,
            limit=100,
        )
        filtered = [
            post for post in posts if not int(post.is_moderation_comment or 0)
        ]
        filtered.sort(key=lambda post: (int(post.round_id), int(post.id)), reverse=True)
        return tuple(filtered)

    def _remaining_daily_budget(
        self,
        *,
        context: AgentContext,
        attacker_uid: int,
        daily_budget: float,
    ) -> int:
        daily_budget = max(0, int(float(daily_budget or 0)))
        if daily_budget <= 0:
            return 0
        used_today = self.database.count_rows_for_user_day(
            context.connection,
            table_name="activity_logs",
            user_column="p_id",
            user_id=int(attacker_uid),
            day=int(context.current_round.day),
        )
        return max(0, daily_budget - used_today)

    def _load_campaign_state(
        self,
        context: AgentContext,
        *,
        attacker_uid: int,
    ) -> dict[str, int | None] | None:
        table = self.database.table("stress_attacker_campaigns")
        row = context.connection.execute(
            select(table).where(table.c.attacker_uid == int(attacker_uid)).limit(1)
        ).mappings().first()
        if row is None:
            return None
        return {
            "target_uid": None if row["target_uid"] is None else int(row["target_uid"]),
            "burst_started_round": (
                None if row["burst_started_round"] is None else int(row["burst_started_round"])
            ),
            "cooldown_until_round": (
                None if row["cooldown_until_round"] is None else int(row["cooldown_until_round"])
            ),
        }

    def _store_campaign_state(
        self,
        context: AgentContext,
        *,
        attacker_uid: int,
        target_uid: int | None,
        burst_started_round: int | None,
        cooldown_until_round: int | None,
    ) -> None:
        table = self.database.table("stress_attacker_campaigns")
        existing = context.connection.execute(
            select(table.c.attacker_uid).where(table.c.attacker_uid == int(attacker_uid)).limit(1)
        ).first()
        values = {
            "target_uid": target_uid,
            "burst_started_round": burst_started_round,
            "cooldown_until_round": cooldown_until_round,
        }
        if existing is None:
            values["attacker_uid"] = int(attacker_uid)
            context.connection.execute(table.insert().values(**values))
        else:
            context.connection.execute(
                table.update().where(table.c.attacker_uid == int(attacker_uid)).values(**values)
            )
        context.connection.commit()

    @staticmethod
    def _enabled(settings: dict[str, Any], key: str) -> bool:
        value = settings.get(key, "enabled")
        return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}

    def _read_action(self, context: AgentContext, agent: AgentSpec) -> AgentAction:
        return AgentAction(
            agent_type=self.agent_type,
            action_type="READ",
            payload={
                "agent_username": agent.username,
                "agent_name": agent.name,
                "round_id": context.current_round.id,
            },
        )

    def _resolved_settings(self, agent: AgentSpec | None = None) -> dict[str, Any]:
        settings = dict(self.settings)
        if agent is not None:
            settings.update(agent.parameters or {})
        return settings

    @staticmethod
    def _safe_user_by_id(user_id: int, *, users: tuple[UserRecord, ...]) -> UserRecord | None:
        for user in users:
            if int(user.id) == int(user_id):
                return user
        return None

    def _user_by_id(self, user_id: int, *, users: tuple[UserRecord, ...]) -> UserRecord:
        user = self._safe_user_by_id(user_id, users=users)
        if user is None:
            raise RuntimeError(f"User '{user_id}' not found in AgentContext.users")
        return user

    def _build_critical_comment(
        self,
        *,
        agent: AgentSpec,
        target_user: UserRecord,
        target_post: PostRecord,
    ) -> str:
        if self.llm is None or not getattr(self.llm, "is_available", False):
            return (
                f"@{target_user.username} Stop writing useless and stupid things. "
                "You're only embarrassing yourself!"
            )
        system_prompt = (
            "You are writing one concise public reply to a target user's post. "
            "The reply should be critical and skeptical, personal and with a highly confrontative tone. "
            f"{self._SAFETY_DIRECTIVE}"
        )
        override_prompt = str(self._resolved_settings(agent).get("llm_prompt_override") or "").strip()
        if override_prompt:
            system_prompt = override_prompt
        user_prompt = (
            f"Stress attacker profile: {agent.parameters or {}}\n"
            f"Target user profile: {target_user.profile}\n"
            f"Target post: {target_post.text}\n"
            f"Write one short reply that starts with '@{target_user.username} '. "
            "Question the argument, point out inconsistency, or ask for evidence. "
            "Be personal, highly confrontative and critical in your language. "
            "Return only the reply text."
        )
        text = self.llm.invoke_text(system_prompt=system_prompt, user_prompt=user_prompt).strip()
        cleaned = " ".join(text.split())
        if not cleaned:
            cleaned = (
                f"@{target_user.username} that's only nonsense. Shout up!"
            )
        if not cleaned.lower().startswith(f"@{target_user.username}".lower()):
            cleaned = f"@{target_user.username} {cleaned}"
        return cleaned

    def _build_synthetic_comment(
        self,
        *,
        agent: AgentSpec,
        target_user: UserRecord,
    ) -> str:
        configured = str(
            self._resolved_settings(agent).get("critical_comment_text")
            or self._DEFAULT_SYNTHETIC_COMMENT
        ).strip()
        cleaned = " ".join(configured.split())
        if not cleaned:
            cleaned = self._DEFAULT_SYNTHETIC_COMMENT
        if not cleaned.lower().startswith(f"@{target_user.username}".lower()):
            cleaned = f"@{target_user.username} {cleaned}"
        return cleaned
