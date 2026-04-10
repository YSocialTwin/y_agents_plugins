from __future__ import annotations

import re

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, text

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec, PostRecord
from y_agents_plugins.plugins.base import BaseAgentPlugin


class ModeratorAgent(BaseAgentPlugin):
    """Example moderator plugin with a restricted moderation-oriented action space."""

    agent_type = "moderator"

    def setup_database(self, database, connection) -> None:
        super().setup_database(database, connection)
        if self.settings:
            self._validate_settings(self._resolved_settings())
        metadata = MetaData()
        sys_messages = Table(
            "sys_messages",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("type", Text, nullable=False),
            Column("to_uid", Integer, nullable=True),
            Column("message", Text, nullable=False),
            Column("from_round", Integer, nullable=True),
            Column("duration", Integer, nullable=True),
        )
        moderation_actions = Table(
            "plugin_moderation_actions",
            metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("moderated_post_id", Integer, nullable=False),
            Column("moderated_agent_id", Integer, nullable=False),
            Column("moderator_agent_id", Integer, nullable=False),
            Column("moderation_type", String(100), nullable=False),
            Column("round_id", Integer, nullable=False),
            Column("generated_comment_id", Integer, nullable=True),
        )
        moderation_counts = Table(
            "plugin_moderation_counts",
            metadata,
            Column("moderated_agent_id", Integer, primary_key=True),
            Column("moderation_count", Integer, nullable=False, default=0),
        )
        moderation_strategies = Table(
            "plugin_moderation_strategies",
            metadata,
            Column("strategy_key", String(100), primary_key=True),
            Column("description", Text, nullable=False),
        )
        shadow_ban = Table(
            "shadow_ban",
            metadata,
            Column("uid", Integer, primary_key=True),
            Column("start_tid", Integer, primary_key=True),
            Column("duration", Integer, nullable=False),
        )
        banned = Table(
            "banned",
            metadata,
            Column("uid", Integer, primary_key=True),
            Column("tid", Integer, nullable=False),
        )
        tables = (
            sys_messages,
            moderation_actions,
            moderation_counts,
            moderation_strategies,
        )
        if self._shadow_ban_enabled(self._resolved_settings()):
            tables = tables + (shadow_ban,)
        if self._ban_enabled(self._resolved_settings()):
            tables = tables + (banned,)
        for table in tables:
            if not database.has_table(connection, table.name):
                table.create(connection, checkfirst=True)
        if self._ban_enabled(self._resolved_settings()):
            user_mgmt_columns = database._table_columns(connection, "user_mgmt")
            if "left_on" not in user_mgmt_columns:
                connection.execute(text("ALTER TABLE user_mgmt ADD COLUMN left_on INTEGER"))
                connection.commit()
                database._reflected_tables.pop("user_mgmt", None)
        connection.commit()
        database.seed_table_rows(
            connection,
            "plugin_moderation_strategies",
            rows=self._moderation_strategies(),
            key_column="strategy_key",
        )

    def on_tick(self, context: AgentContext, agent: AgentSpec) -> list[AgentAction]:
        settings = self._resolved_settings(agent)
        self._validate_settings(settings)
        if self._daily_budget_exhausted(context, agent):
            return [
                AgentAction(
                    agent_type=self.agent_type,
                    action_type="READ",
                    payload={
                        "agent_username": agent.username,
                        "agent_name": agent.name,
                        "round_id": context.current_round.id,
                    },
                )
            ]
        candidate = self._select_candidate(context, settings=settings)
        if candidate is None:
            return [
                AgentAction(
                    agent_type=self.agent_type,
                    action_type="READ",
                    payload={
                        "agent_username": agent.username,
                        "agent_name": agent.name,
                        "round_id": context.current_round.id,
                    },
                )
            ]

        return [
            AgentAction(
                agent_type=self.agent_type,
                action_type="READ",
                payload={
                    "agent_username": agent.username,
                    "agent_name": agent.name,
                    "post_id": candidate.id,
                    "round_id": context.current_round.id,
                },
            ),
            AgentAction(
                agent_type=self.agent_type,
                action_type="APPLY_MODERATION",
                payload=self._build_moderation_payload(
                    context=context,
                    agent=agent,
                    post=candidate,
                    settings=settings,
                ),
            ),
        ]

    def _daily_budget_exhausted(self, context: AgentContext, agent: AgentSpec) -> bool:
        if context.connection is None:
            return False
        daily_budget = max(0, int(float(agent.daily_budget)))
        if daily_budget <= 0:
            return True
        used_today = self.database.count_moderations_for_agent_day(
            context.connection,
            moderator_username=agent.username,
            day=int(context.current_round.day),
        )
        return used_today >= daily_budget

    def _moderation_strategies(self) -> list[dict[str, str]]:
        configured = self.settings.get("moderation_strategies")
        if isinstance(configured, list) and configured:
            return [
                {
                    "strategy_key": str(item["strategy_key"]),
                    "description": str(item["description"]),
                }
                for item in configured
            ]
        return [
            {
                "strategy_key": "one-fits-all",
                "description": "Write a standard moderation notice into sys_messages and mark the post as moderated.",
            },
            {
                "strategy_key": "personalized",
                "description": "Generate a user-tailored moderation notice with the LangChain LLM, write it into sys_messages, and mark the post as moderated.",
            }
        ]
    
    def _select_candidate(
        self,
        context: AgentContext,
        *,
        settings: dict[str, object],
    ) -> PostRecord | None:
        lookback_rounds = int(settings.get("candidate_window_rounds", 1))
        threshold = float(settings["toxicity_threshold"])
        candidates = [
            post
            for post in context.recent_posts
            if post.moderated == 0
            and post.is_moderation_comment == 0
            and (context.current_round.id - post.round_id) <= lookback_rounds
            and (post.reported_count > 0 or float(post.toxicity or 0.0) >= threshold)
            and not self._target_is_banned(context, post.author_id)
        ]
        if not candidates:
            return None
        return max(
            candidates,
            key=lambda post: (
                int(post.reported_count > 0),
                int(post.reported_count),
                float(post.toxicity or 0.0),
                int(post.round_id),
                int(post.id),
            ),
        )

    def _build_moderation_payload(
        self,
        *,
        context: AgentContext,
        agent: AgentSpec,
        post: PostRecord,
        settings: dict[str, object],
    ) -> dict[str, object]:
        target_user = self._user_by_id(post.author_id, users=context.users)
        message = self._build_system_message(
            post=post,
            target_user=target_user,
            moderator=agent,
            settings=settings,
            context=context,
        )
        shadow_ban_infraction_count = self._infraction_count_for_window(
            context=context,
            target_user_id=post.author_id,
            window_rounds=int(settings.get("shadow_ban_infraction_window_rounds", 24) or 24),
        )
        ban_infraction_count = self._infraction_count_for_window(
            context=context,
            target_user_id=post.author_id,
            window_rounds=int(settings.get("ban_infraction_window_rounds", 24) or 24),
        )
        shadow_ban_applied = self._shadow_ban_enabled(settings) and self._should_apply_shadow_ban(
            infraction_count=shadow_ban_infraction_count,
            settings=settings,
        )
        ban_warning = self._ban_enabled(settings) and self._should_warn_ban(
            infraction_count=ban_infraction_count,
            settings=settings,
        )
        ban_applied = self._ban_enabled(settings) and self._should_apply_ban(
            infraction_count=ban_infraction_count,
            settings=settings,
        )
        return {
            "agent_username": agent.username,
            "agent_name": agent.name,
            "post_id": post.id,
            "target_user_id": post.author_id,
            "round_id": context.current_round.id,
            "reason": settings["moderation_action_type"],
            "system_message_text": message,
            "message_type": "moderation",
            "message_duration": int(settings["moderation_time_span"]),
            "infraction_count": max(shadow_ban_infraction_count, ban_infraction_count),
            "shadow_ban_infraction_count": shadow_ban_infraction_count,
            "ban_infraction_count": ban_infraction_count,
            "shadow_ban_enabled": self._shadow_ban_enabled(settings),
            "shadow_ban_applied": shadow_ban_applied,
            "shadow_ban_duration": int(settings.get("shadow_ban_duration_rounds", 0) or 0),
            "ban_enabled": self._ban_enabled(settings),
            "ban_warning": ban_warning,
            "ban_applied": ban_applied,
        }

    def _build_system_message(
        self,
        *,
        post: PostRecord,
        target_user,
        moderator: AgentSpec,
        settings: dict[str, object],
        context: AgentContext,
    ) -> str:
        shadow_ban_infraction_count = self._infraction_count_for_window(
            context=context,
            target_user_id=post.author_id,
            window_rounds=int(settings.get("shadow_ban_infraction_window_rounds", 24) or 24),
        )
        ban_infraction_count = self._infraction_count_for_window(
            context=context,
            target_user_id=post.author_id,
            window_rounds=int(settings.get("ban_infraction_window_rounds", 24) or 24),
        )
        shadow_ban_enabled = self._shadow_ban_enabled(settings)
        ban_enabled = self._ban_enabled(settings)
        escalation_notice = (
            self._shadow_ban_notice(
                infraction_count=shadow_ban_infraction_count,
                settings=settings,
            )
            if shadow_ban_enabled
            else ""
        )
        ban_notice = (
            self._ban_notice(
                infraction_count=ban_infraction_count,
                settings=settings,
            )
            if ban_enabled
            else ""
        )
        if settings["moderation_action_type"] == "one-fits-all":
            if not shadow_ban_enabled and not ban_enabled:
                return "Your recent post violated the platform moderation policy. Please adjust your behavior."
            return " ".join(
                part
                for part in (
                    "Your recent post violated the platform moderation policy.",
                    (
                        f"This is infraction {max(shadow_ban_infraction_count, ban_infraction_count)}."
                        if (shadow_ban_enabled or ban_enabled)
                        else ""
                    ),
                    "Please adjust your behavior.",
                    escalation_notice,
                    ban_notice,
                )
                if part
            )
        if self.llm is None or not self.llm.is_available:
            raise ValueError("moderation_action_type 'personalized' requires a configured LangChain LLM model")
        system_prompt = (
            "You are a moderation assistant for a YSocial simulation. "
            "Write one short personalized moderation notice for the offending user. "
            "Be firm, concise, and mention the behavior change expected. "
            "Do not add any heading, salutation, recipient line, timeframe sentence, or signature. "
        )
        if shadow_ban_enabled:
            system_prompt += (
                "Explicitly mention the user's current infraction count. "
                "If provided, mention the risk of a temporary shadow ban or the fact that the ban has been triggered."
            )
        if ban_enabled:
            system_prompt += (
                " If provided, mention whether the user has reached the permanent-ban warning threshold or has now been permanently banned."
            )
        user_prompt = (
            f"Moderator: {moderator.name}\n"
            f"Moderated post id: {post.id}\n"
            f"Post text: {post.text}\n"
            f"Target user profile: {target_user.profile}\n"
            f"Current shadow-ban infraction count: {shadow_ban_infraction_count if shadow_ban_enabled else 'not applicable'}\n"
            f"Current permanent-ban infraction count: {ban_infraction_count if ban_enabled else 'not applicable'}\n"
            f"Escalation notice: {escalation_notice or 'No shadow-ban escalation is configured.'}\n"
            f"Ban notice: {ban_notice or 'No permanent-ban escalation is configured.'}\n"
            "Return only the moderation notice body."
        )
        return self._clean_personalized_message(
            self.llm.invoke_text(system_prompt=system_prompt, user_prompt=user_prompt)
        )

    def _user_by_id(self, user_id: int, *, users):
        for user in users:
            if user.id == user_id:
                return user
        raise RuntimeError(f"User '{user_id}' not found in AgentContext.users")

    def _resolved_settings(self, agent: AgentSpec | None = None) -> dict[str, object]:
        settings = dict(self.settings)
        if agent is not None:
            settings.update(agent.parameters or {})
        return settings

    def _infraction_count_for_window(
        self,
        *,
        context: AgentContext,
        target_user_id: int,
        window_rounds: int,
    ) -> int:
        if context.connection is None:
            return 1
        previous = self.database.count_recent_infractions_for_user(
            context.connection,
            user_id=int(target_user_id),
            current_round_id=int(context.current_round.id),
            window_rounds=max(0, int(window_rounds)),
        )
        return previous + 1

    def _target_is_banned(self, context: AgentContext, target_user_id: int) -> bool:
        if context.connection is None:
            return False
        return self.database.user_is_banned(
            context.connection,
            user_id=int(target_user_id),
        )

    def _shadow_ban_enabled(self, settings: dict[str, object]) -> bool:
        raw = str(settings.get("shadow_ban_enabled", "disabled")).strip().lower()
        return raw in {"enabled", "true", "1", "yes", "on"}

    def _ban_enabled(self, settings: dict[str, object]) -> bool:
        raw = str(settings.get("ban_enabled", "disabled")).strip().lower()
        return raw in {"enabled", "true", "1", "yes", "on"}

    def _should_apply_shadow_ban(
        self,
        *,
        infraction_count: int,
        settings: dict[str, object],
    ) -> bool:
        if not self._shadow_ban_enabled(settings):
            return False
        threshold = int(settings.get("shadow_ban_n_infraction", 0) or 0)
        duration = int(settings.get("shadow_ban_duration_rounds", 0) or 0)
        return threshold > 0 and duration > 0 and int(infraction_count) >= threshold

    def _shadow_ban_notice(
        self,
        *,
        infraction_count: int,
        settings: dict[str, object],
    ) -> str:
        if not self._shadow_ban_enabled(settings):
            return ""
        threshold = int(settings.get("shadow_ban_n_infraction", 0) or 0)
        duration = int(settings.get("shadow_ban_duration_rounds", 0) or 0)
        if threshold <= 0 or duration <= 0:
            return ""
        if infraction_count >= threshold:
            return (
                f"You have reached the moderation threshold and are now under a temporary shadow ban for {duration} rounds."
            )
        remaining = threshold - int(infraction_count)
        return (
            f"If you reach {threshold} infractions within the configured window, your content may be shadow-banned for {duration} rounds. "
            f"{remaining} infraction{'s' if remaining != 1 else ''} remain before that threshold."
        )

    def _should_warn_ban(
        self,
        *,
        infraction_count: int,
        settings: dict[str, object],
    ) -> bool:
        if not self._ban_enabled(settings):
            return False
        threshold = int(settings.get("ban_n_infraction", 0) or 0)
        return threshold > 0 and int(infraction_count) == threshold

    def _should_apply_ban(
        self,
        *,
        infraction_count: int,
        settings: dict[str, object],
    ) -> bool:
        if not self._ban_enabled(settings):
            return False
        threshold = int(settings.get("ban_n_infraction", 0) or 0)
        return threshold > 0 and int(infraction_count) > threshold

    def _ban_notice(
        self,
        *,
        infraction_count: int,
        settings: dict[str, object],
    ) -> str:
        if not self._ban_enabled(settings):
            return ""
        threshold = int(settings.get("ban_n_infraction", 0) or 0)
        if threshold <= 0:
            return ""
        if infraction_count > threshold:
            return "You have exceeded the permanent-ban threshold and are now permanently banned from the platform."
        if infraction_count == threshold:
            return "You have reached the permanent-ban warning threshold. Your next infraction within the configured window will result in a permanent ban."
        remaining = threshold - int(infraction_count)
        return (
            f"If you reach {threshold} infractions within the configured window, your next infraction after that threshold will result in a permanent ban. "
            f"{remaining} infraction{'s' if remaining != 1 else ''} remain before the warning threshold."
        )

    def _clean_personalized_message(self, message: str) -> str:
        cleaned = str(message or "").strip()
        cleaned = re.sub(
            r"^\s*\*\*To [^\n]+\*\*\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"Please be aware that your comment was reviewed[^\n]*\n*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\n?\s*(Sincerely|Regards|Best),?\s*\n.*$",
            "",
            cleaned,
            flags=re.IGNORECASE | re.DOTALL,
        )
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _validate_settings(self, settings: dict[str, object]) -> None:
        required = ("toxicity_threshold", "moderation_time_span", "moderation_action_type")
        missing = [name for name in required if name not in settings]
        if missing:
            raise ValueError(f"Moderator settings missing required fields: {missing}")
        threshold = float(settings["toxicity_threshold"])
        if threshold < 0 or threshold > 1:
            raise ValueError("toxicity_threshold must be in [0, 1]")
        time_span = int(settings["moderation_time_span"])
        if time_span <= 0:
            raise ValueError("moderation_time_span must be > 0")
        strategy = str(settings["moderation_action_type"])
        if strategy not in {"one-fits-all", "personalized"}:
            raise ValueError("moderation_action_type must be 'one-fits-all' or 'personalized'")
        if strategy == "personalized" and (self.llm is None or not self.llm.is_available):
            raise ValueError("moderation_action_type 'personalized' requires a configured LangChain LLM model")
        if self._shadow_ban_enabled(settings):
            infraction_window = int(settings.get("shadow_ban_infraction_window_rounds", 24) or 24)
            infraction_threshold = int(settings.get("shadow_ban_n_infraction", 0) or 0)
            shadow_ban_duration = int(settings.get("shadow_ban_duration_rounds", 0) or 0)
            if infraction_window <= 0:
                raise ValueError("shadow_ban_infraction_window_rounds must be > 0 when shadow ban is enabled")
            if infraction_threshold <= 0:
                raise ValueError("shadow_ban_n_infraction must be > 0 when shadow ban is enabled")
            if shadow_ban_duration <= 0:
                raise ValueError("shadow_ban_duration_rounds must be > 0 when shadow ban is enabled")
        if self._ban_enabled(settings):
            infraction_window = int(settings.get("ban_infraction_window_rounds", 24) or 24)
            infraction_threshold = int(settings.get("ban_n_infraction", 0) or 0)
            if infraction_window <= 0:
                raise ValueError("ban_infraction_window_rounds must be > 0 when ban is enabled")
            if infraction_threshold <= 0:
                raise ValueError("ban_n_infraction must be > 0 when ban is enabled")
