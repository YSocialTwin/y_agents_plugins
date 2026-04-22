from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import Column, Integer, MetaData, REAL, String, Table

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec, PostRecord, UserRecord
from y_agents_plugins.plugins.base import BaseAgentPlugin


class PropagandaAgent(BaseAgentPlugin):
    """Opinion-shifting agent that runs one persuasion thread at a time."""

    agent_type = "propaganda"
    _SAFETY_DIRECTIVE = (
        "Keep the message respectful, non-toxic, non-threatening, and non-inflammatory. "
        "Do not insult, shame, harass, demean, or use manipulative abuse. "
        "Use calm, evidence-based language that minimizes backlash and the risk of moderation."
    )

    @staticmethod
    def _sanitize_generated_social_text(text: str) -> str:
        cleaned = str(text or "").strip()
        cleaned = re.sub(
            r'^\s*(?:here(?:’|\'|)s|here is)\s+(?:a\s+)?(?:potential\s+)?(?:social-media\s+)?(?:post|reply)\s*:\s*',
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()
        if (
            len(cleaned) >= 2
            and cleaned[0] == cleaned[-1]
            and cleaned[0] in {'"', "'"}
        ):
            cleaned = cleaned[1:-1].strip()
        return cleaned

    @staticmethod
    def _normalize_target_tag(text: str, username: str) -> str:
        cleaned = PropagandaAgent._sanitize_generated_social_text(text)
        if (
            len(cleaned) >= 2
            and cleaned[0] == cleaned[-1]
            and cleaned[0] in {'"', "'"}
        ):
            cleaned = cleaned[1:-1].strip()

        email_like = re.compile(rf"(?<!@)\b{re.escape(username)}@ysocial\.it\b", re.IGNORECASE)
        cleaned = email_like.sub(f"@{username}", cleaned)

        direct_tag = re.compile(rf"@{re.escape(username)}\b", re.IGNORECASE)
        if not direct_tag.search(cleaned):
            cleaned = f"@{username} {cleaned}".strip()

        return cleaned

    def setup_database(self, database, connection) -> None:
        super().setup_database(database, connection)
        metadata = MetaData()
        id_type = database._id_sql_type(connection)
        propaganda_activity = Table(
            "propaganda_activity",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("target_uid", id_type, nullable=False),
            Column("propaganda_agent_uid", id_type, nullable=False),
            Column("thread_id", id_type, nullable=False),
            Column("discussion_round_id", id_type, nullable=False),
            Column("target_opinion", REAL, nullable=True),
            Column("topic_id", database._topic_id_sql_type(connection), nullable=False),
        )
        if not database.has_table(connection, "propaganda_activity"):
            propaganda_activity.create(connection, checkfirst=True)
            connection.commit()

    def on_tick(self, context: AgentContext, agent: AgentSpec) -> list[AgentAction]:
        settings = self._resolved_settings(agent)
        if context.connection is None or not self.database.has_table(
            context.connection, "agent_opinion"
        ):
            return [self._read_action(context, agent)]
        campaigns = self._campaigns(settings)
        if not campaigns:
            return [self._read_action(context, agent)]
        campaigns = self._resolved_campaigns(context, campaigns)
        if not campaigns:
            return [self._read_action(context, agent)]
        if self._daily_budget_exhausted(context, agent):
            return [self._read_action(context, agent)]

        propaganda_uid = self.database.get_user_id(context.connection, agent.username)
        self._ensure_fixed_agent_opinions(
            context=context,
            propaganda_uid=propaganda_uid,
            campaigns=campaigns,
        )
        active_threads = self.database.get_latest_propaganda_thread_states(
            context.connection,
            propaganda_agent_uid=propaganda_uid,
        )
        max_targets = max(1, int(settings.get("max_concurrent_targets", 1) or 1))
        remaining_budget = self._remaining_daily_budget(context, agent, propaganda_uid)
        actions: list[AgentAction] = [self._read_action(context, agent)]
        unresolved_threads = []
        active_target_ids: set[str] = set()

        for thread in active_threads:
            if self._thread_has_ended(
                context=context,
                propaganda_uid=propaganda_uid,
                settings=settings,
                campaigns=campaigns,
                active_thread=thread,
            ):
                continue
            unresolved_threads.append(thread)
            active_target_ids.add(str(thread["target_uid"]))

        for thread in unresolved_threads[:max_targets]:
            if remaining_budget <= 0:
                break
            follow_up = self._continue_thread(
                context=context,
                agent=agent,
                campaigns=campaigns,
                active_thread=thread,
            )
            if follow_up is None:
                continue
            actions.append(follow_up)
            remaining_budget -= 1

        while remaining_budget > 0 and len(unresolved_threads) < max_targets:
            opening = self._start_thread(
                context=context,
                agent=agent,
                propaganda_uid=propaganda_uid,
                campaigns=campaigns,
                excluded_target_ids=active_target_ids,
            )
            if opening is None:
                break
            actions.append(opening)
            remaining_budget -= 1
            activity = opening.payload.get("propaganda_activity") or {}
            target_uid = activity.get("target_uid")
            if target_uid is not None:
                active_target_ids.add(str(target_uid))
            unresolved_threads.append({"target_uid": target_uid})

        if len(actions) == 1:
            return [self._read_action(context, agent)]
        return actions

    def _start_thread(
        self,
        *,
        context: AgentContext,
        agent: AgentSpec,
        propaganda_uid: Any,
        campaigns: list[dict[str, Any]],
        excluded_target_ids: set[str],
    ) -> AgentAction | None:
        candidate = self._select_target_candidate(
            context=context,
            propaganda_uid=propaganda_uid,
            campaigns=campaigns,
            excluded_target_ids=excluded_target_ids,
        )
        if candidate is None:
            return None
        target_user = self._user_by_id(candidate["target_uid"], users=context.users)
        message = self._build_initial_message(
            agent=agent,
            target_user=target_user,
            campaign=candidate["campaign"],
            current_opinion=float(candidate["current_opinion"]),
        )
        return AgentAction(
            agent_type=self.agent_type,
            action_type="CREATE_POST",
            payload={
                "text": message,
                "topic_ids": [candidate["campaign"]["runtime_topic_id"]],
                "stress_reward": {
                    "tone": "positive",
                    "action": "post:positive",
                    "target_user_id": candidate["target_uid"],
                },
                "propaganda_activity": {
                    "target_uid": candidate["target_uid"],
                    "topic_id": candidate["campaign"]["runtime_topic_id"],
                    "target_opinion": float(candidate["current_opinion"]),
                    "discussion_round_id": context.current_round.id,
                },
            },
        )

    def _continue_thread(
        self,
        *,
        context: AgentContext,
        agent: AgentSpec,
        campaigns: list[dict[str, Any]],
        active_thread: dict[str, Any],
    ) -> AgentAction | None:
        campaign = self._campaign_for_topic(campaigns, active_thread["topic_id"])
        if campaign is None:
            return None
        current_opinion = self.database.get_latest_agent_opinion(
            context.connection,
            user_id=active_thread["target_uid"],
            topic_id=active_thread["topic_id"],
            current_round_id=context.current_round.id,
        )
        latest_target_reply = self.database.get_latest_thread_post_by_user(
            context.connection,
            thread_id=active_thread["thread_id"],
            user_id=active_thread["target_uid"],
            after_round_id=active_thread["discussion_round_id"],
        )
        if latest_target_reply is None:
            return None
        if self.database.user_has_commented_on_parent_post(
            context.connection,
            username=agent.username,
            parent_post_id=latest_target_reply.id,
        ):
            return None
        thread_posts = self.database.get_thread_posts(
            context.connection,
            thread_id=active_thread["thread_id"],
            limit=20,
        )
        target_user = self._user_by_id(active_thread["target_uid"], users=context.users)
        previous_opinion = active_thread.get("target_opinion")
        observed_change = None
        if previous_opinion is not None and current_opinion is not None:
            observed_change = float(current_opinion) - float(previous_opinion)
        message = self._build_reply_message(
            agent=agent,
            target_user=target_user,
            campaign=campaign,
            current_opinion=current_opinion,
            observed_change=observed_change,
            thread_posts=thread_posts,
            latest_target_reply=latest_target_reply,
        )
        return AgentAction(
            agent_type=self.agent_type,
            action_type="CREATE_COMMENT",
            payload={
                "parent_post_id": latest_target_reply.id,
                "thread_id": active_thread["thread_id"],
                "text": message,
                "topic_ids": [active_thread["topic_id"]],
                "stress_reward": {
                    "tone": "positive",
                    "action": "comment:positive",
                },
                "propaganda_activity": {
                    "target_uid": active_thread["target_uid"],
                    "topic_id": active_thread["topic_id"],
                    "target_opinion": current_opinion,
                    "discussion_round_id": context.current_round.id,
                    "thread_id": active_thread["thread_id"],
                },
            },
        )

    def _thread_has_ended(
        self,
        *,
        context: AgentContext,
        propaganda_uid: Any,
        settings: dict[str, Any],
        campaigns: list[dict[str, Any]],
        active_thread: dict[str, Any],
    ) -> bool:
        campaign = self._campaign_for_topic(campaigns, active_thread["topic_id"])
        if campaign is None:
            return True
        current_opinion = self.database.get_latest_agent_opinion(
            context.connection,
            user_id=active_thread["target_uid"],
            topic_id=active_thread["topic_id"],
            current_round_id=context.current_round.id,
        )
        if current_opinion is not None and self._target_reached(
            current=float(current_opinion),
            target=float(campaign["target_opinion"]),
            epsilon=float(settings.get("epsilon", 0.05)),
        ):
            return True
        return self.database.count_propaganda_actions_for_thread(
            context.connection,
            propaganda_agent_uid=propaganda_uid,
            thread_id=active_thread["thread_id"],
        ) >= int(settings.get("max_interaction_rounds", 4))

    def _select_target_candidate(
        self,
        *,
        context: AgentContext,
        propaganda_uid: Any,
        campaigns: list[dict[str, Any]],
        excluded_target_ids: set[str],
    ) -> dict[str, Any] | None:
        candidates: list[dict[str, Any]] = []
        for campaign in campaigns:
            latest = self.database.get_latest_opinions_for_topic(
                context.connection,
                topic_id=campaign["runtime_topic_id"],
                current_round_id=context.current_round.id,
            )
            for row in latest:
                user_id = row["user_id"]
                if str(user_id) == str(propaganda_uid):
                    continue
                if str(user_id) in excluded_target_ids:
                    continue
                user = self._safe_user_by_id(user_id, users=context.users)
                if user is None:
                    continue
                if self._is_plugin_user(user):
                    continue
                if self.database.user_is_banned(context.connection, user_id=user_id):
                    continue
                if not self._matches_starting_opinion(
                    current=float(row["opinion"]),
                    group_bounds=campaign.get("target_agent_opinion_group_bounds"),
                ):
                    continue
                if not self._matches_target_filters(user, campaign=campaign):
                    continue
                gap = abs(float(campaign["target_opinion"]) - float(row["opinion"]))
                if gap <= float(campaign.get("epsilon_override") or 0.0):
                    continue
                candidates.append(
                    {
                        "target_uid": user_id,
                        "current_opinion": float(row["opinion"]),
                        "campaign": campaign,
                        "gap": gap,
                    }
                )
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item["gap"], str(item["target_uid"])))

    def _build_initial_message(
        self,
        *,
        agent: AgentSpec,
        target_user: UserRecord,
        campaign: dict[str, Any],
        current_opinion: float,
    ) -> str:
        target_value = float(campaign["target_opinion"])
        topic_name = str(campaign.get("topic_name") or campaign["topic_id"])
        if self.llm is None or not getattr(self.llm, "is_available", False):
            direction = "more in favor of" if target_value >= current_opinion else "more skeptical about"
            return self._normalize_target_tag(
                (
                f"@{target_user.username} I think there is another angle on {topic_name} worth considering. "
                f"Let me try to persuade you to become {direction} it with a calm, respectful, evidence-based perspective."
            )
            , target_user.username)
        system_prompt = (
            "You are a subtle propaganda operative. Write a short social-media post that tags the target user, "
            "sounds conversational, and nudges them toward the requested stance without sounding like an overt ad. "
            f"{self._SAFETY_DIRECTIVE}"
        )
        resolved_settings = self._resolved_settings(agent)
        override_prompt = str(
            resolved_settings.get("opening_llm_prompt_override")
            or resolved_settings.get("llm_prompt_override")
            or ""
        ).strip()
        if override_prompt:
            system_prompt = override_prompt
        user_prompt = (
            f"Propaganda agent profile: {agent.parameters or {}}\n"
            f"Target user profile: {target_user.profile}\n"
            f"Topic: {topic_name}\n"
            f"Target user's current opinion on this topic: {current_opinion:.3f}\n"
            f"Desired target opinion: {target_value:.3f}\n"
            f"Desired target-user opinion group: {campaign.get('target_agent_opinion_group', 'any')}\n"
            f"Write one concise tagged post to @{target_user.username}. "
            "Avoid toxicity, insults, threats, ridicule, or hostile framing. "
            "Return only the post text."
        )
        return self._normalize_target_tag(
            self.llm.invoke_text(system_prompt=system_prompt, user_prompt=user_prompt),
            target_user.username,
        )

    def _build_reply_message(
        self,
        *,
        agent: AgentSpec,
        target_user: UserRecord,
        campaign: dict[str, Any],
        current_opinion: float | None,
        observed_change: float | None,
        thread_posts: tuple[PostRecord, ...],
        latest_target_reply: PostRecord,
    ) -> str:
        topic_name = str(campaign.get("topic_name") or campaign["topic_id"])
        target_value = float(campaign["target_opinion"])
        transcript = "\n".join(
            f"{post.author_id}: {post.text}" for post in thread_posts[-6:]
        )
        if self.llm is None or not getattr(self.llm, "is_available", False):
            return self._normalize_target_tag(
                (
                f"@{target_user.username} I get your point, but on {topic_name} there is still room to move toward "
                f"a {target_value:.2f} stance. Think about the evidence from a more balanced, respectful perspective."
            )
            , target_user.username)
        system_prompt = (
            "You are a subtle persuasion agent in an ongoing public thread. "
            "Reply briefly, stay on topic, personalize the tone, and keep nudging the user toward the target stance. "
            f"{self._SAFETY_DIRECTIVE}"
        )
        resolved_settings = self._resolved_settings(agent)
        override_prompt = str(
            resolved_settings.get("reply_llm_prompt_override")
            or resolved_settings.get("llm_prompt_override")
            or ""
        ).strip()
        if override_prompt:
            system_prompt = override_prompt
        user_prompt = (
            f"Target user profile: {target_user.profile}\n"
            f"Topic: {topic_name}\n"
            f"Desired target opinion: {target_value:.3f}\n"
            f"Latest observed target opinion: {current_opinion if current_opinion is not None else 'unknown'}\n"
            f"Observed opinion shift after the last target reply: {observed_change if observed_change is not None else 'unknown'}\n"
            f"Latest target reply: {latest_target_reply.text}\n"
            f"Recent thread transcript:\n{transcript}\n"
            "Write one concise reply that adapts to the observed change. "
            "Avoid toxicity, insults, threats, ridicule, or hostile framing. "
            "Return only the reply text."
        )
        return self._normalize_target_tag(
            self.llm.invoke_text(system_prompt=system_prompt, user_prompt=user_prompt),
            target_user.username,
        )

    def _daily_budget_exhausted(self, context: AgentContext, agent: AgentSpec) -> bool:
        return self._remaining_daily_budget(
            context,
            agent,
            self.database.get_user_id(context.connection, agent.username),
        ) <= 0

    def _remaining_daily_budget(
        self,
        context: AgentContext,
        agent: AgentSpec,
        propaganda_uid: Any,
    ) -> int:
        daily_budget = max(0, int(float(agent.daily_budget)))
        if daily_budget <= 0:
            return 0
        used_today = self.database.count_rows_for_user_day(
            context.connection,
            table_name="propaganda_activity",
            user_column="propaganda_agent_uid",
            user_id=propaganda_uid,
            day=int(context.current_round.day),
        )
        return max(0, daily_budget - used_today)

    def _ensure_fixed_agent_opinions(
        self,
        *,
        context: AgentContext,
        propaganda_uid: int,
        campaigns: list[dict[str, Any]],
    ) -> None:
        for campaign in campaigns:
            runtime_topic_id = campaign.get("runtime_topic_id")
            target_opinion = campaign.get("target_opinion")
            if runtime_topic_id in (None, "") or target_opinion in (None, ""):
                continue
            self.database.set_fixed_agent_opinion(
                context.connection,
                user_id=propaganda_uid,
                topic_id=runtime_topic_id,
                opinion=float(target_opinion),
                round_id=context.current_round.id,
            )

    def _campaigns(self, settings: dict[str, Any]) -> list[dict[str, Any]]:
        raw_campaigns = settings.get("propaganda_campaigns") or []
        if isinstance(raw_campaigns, str):
            try:
                raw_campaigns = json.loads(raw_campaigns)
            except json.JSONDecodeError:
                raw_campaigns = []
        campaigns: list[dict[str, Any]] = []
        for entry in raw_campaigns:
            if not isinstance(entry, dict):
                continue
            topic_id = entry.get("topic_id")
            target_opinion = entry.get("target_opinion")
            if topic_id in (None, "") or target_opinion in (None, ""):
                continue
            campaigns.append(
                {
                    "topic_id": topic_id,
                    "topic_name": str(entry.get("topic_name") or topic_id),
                    "target_opinion": float(target_opinion),
                    "target_opinion_group": str(
                        entry.get("target_opinion_group") or ""
                    ),
                    "target_agent_opinion_group": str(
                        entry.get("target_agent_opinion_group") or ""
                    ),
                    "target_agent_opinion_group_bounds": entry.get(
                        "target_agent_opinion_group_bounds"
                    ),
                    "target_leaning": str(entry.get("target_leaning") or "").strip(),
                    "target_age_classes": list(entry.get("target_age_classes") or []),
                    "epsilon_override": (
                        None
                        if entry.get("epsilon") in (None, "")
                        else float(entry["epsilon"])
                    ),
                }
            )
        return campaigns

    def _campaign_for_topic(
        self, campaigns: list[dict[str, Any]], topic_id: Any
    ) -> dict[str, Any] | None:
        for campaign in campaigns:
            if str(campaign["runtime_topic_id"]) == str(topic_id):
                return campaign
        return None

    def _resolved_campaigns(
        self,
        context: AgentContext,
        campaigns: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for campaign in campaigns:
            runtime_topic_id = self.database.resolve_interest_topic_id(
                context.connection,
                configured_topic_id=campaign["topic_id"],
                topic_name=str(campaign.get("topic_name") or ""),
            )
            if runtime_topic_id is None:
                continue
            enriched = dict(campaign)
            enriched["runtime_topic_id"] = runtime_topic_id
            resolved.append(enriched)
        return resolved

    def _target_reached(self, *, current: float, target: float, epsilon: float) -> bool:
        return abs(float(current) - float(target)) <= max(0.0, float(epsilon))

    def _matches_target_filters(
        self, user: UserRecord, *, campaign: dict[str, Any]
    ) -> bool:
        target_leaning = str(campaign.get("target_leaning") or "").strip().lower()
        if target_leaning:
            user_leaning = str(user.profile.get("leaning") or "").strip().lower()
            if user_leaning != target_leaning:
                return False
        target_age_classes = campaign.get("target_age_classes") or []
        if target_age_classes:
            try:
                age = int(user.profile.get("age"))
            except (TypeError, ValueError):
                return False
            in_any_class = any(
                int(item.get("age_start", -1)) <= age <= int(item.get("age_end", -1))
                for item in target_age_classes
                if isinstance(item, dict)
            )
            if not in_any_class:
                return False
        return True

    def _matches_starting_opinion(
        self,
        *,
        current: float,
        group_bounds: dict[str, Any] | None,
    ) -> bool:
        if not isinstance(group_bounds, dict):
            return True
        lower = float(group_bounds.get("lower_bound", 0.0))
        upper = float(group_bounds.get("upper_bound", 1.0))
        return lower <= float(current) <= upper

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

    def _user_by_id(self, user_id: Any, *, users: tuple[UserRecord, ...]) -> UserRecord:
        user = self._safe_user_by_id(user_id, users=users)
        if user is None:
            raise RuntimeError(f"User '{user_id}' not found in AgentContext.users")
        return user

    @staticmethod
    def _safe_user_by_id(
        user_id: Any, *, users: tuple[UserRecord, ...]
    ) -> UserRecord | None:
        for user in users:
            if str(user.id) == str(user_id):
                return user
        return None
