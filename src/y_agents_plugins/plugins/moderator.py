from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, String, Table, Text

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec, PostRecord
from y_agents_plugins.plugins.base import BaseAgentPlugin


class ModeratorAgent(BaseAgentPlugin):
    """Example moderator plugin with a restricted moderation-oriented action space."""

    agent_type = "moderator"

    def setup_database(self, database, connection) -> None:
        super().setup_database(database, connection)
        self._validate_settings()
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
        database.create_tables(
            sys_messages,
            moderation_actions,
            moderation_counts,
            moderation_strategies,
        )
        database.seed_table_rows(
            connection,
            "plugin_moderation_strategies",
            rows=self._moderation_strategies(),
            key_column="strategy_key",
        )

    def on_tick(self, context: AgentContext, agent: AgentSpec) -> list[AgentAction]:
        candidate = self._select_candidate(context)
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
                payload=self._build_moderation_payload(context=context, agent=agent, post=candidate),
            ),
        ]

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
    
    def _select_candidate(self, context: AgentContext) -> PostRecord | None:
        lookback_rounds = int(self.settings.get("candidate_window_rounds", 1))
        threshold = float(self.settings["toxicity_threshold"])
        candidates = [
            post
            for post in context.recent_posts
            if post.moderated == 0
            and (context.current_round.id - post.round_id) <= lookback_rounds
            and (post.reported_count > 0 or float(post.toxicity or 0.0) >= threshold)
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
    ) -> dict[str, object]:
        target_user = self._user_by_id(post.author_id, users=context.users)
        message = self._build_system_message(
            post=post,
            target_user=target_user,
            moderator=agent,
        )
        return {
            "agent_username": agent.username,
            "agent_name": agent.name,
            "post_id": post.id,
            "target_user_id": post.author_id,
            "round_id": context.current_round.id,
            "reason": self.settings["moderation_action_type"],
            "system_message_text": message,
            "message_type": "moderation",
            "message_duration": int(self.settings["moderation_time_span"]),
        }

    def _build_system_message(
        self,
        *,
        post: PostRecord,
        target_user,
        moderator: AgentSpec,
    ) -> str:
        if self.settings["moderation_action_type"] == "one-fits-all":
            return (
                "Your recent post violated the platform moderation policy. "
                f"Please adjust your behavior for the next {int(self.settings['moderation_time_span'])} rounds."
            )
        if self.llm is None or not self.llm.is_available:
            raise ValueError("moderation_action_type 'personalized' requires a configured LangChain LLM model")
        system_prompt = (
            "You are a moderation assistant for a YSocial simulation. "
            "Write one short personalized moderation notice for the offending user. "
            "Be firm, concise, and mention the behavior change expected."
        )
        user_prompt = (
            f"Moderator: {moderator.name}\n"
            f"Moderated post id: {post.id}\n"
            f"Post text: {post.text}\n"
            f"Target user profile: {target_user.profile}\n"
            f"Moderation duration: {int(self.settings['moderation_time_span'])} rounds.\n"
            "Return a single concise moderation message."
        )
        return self.llm.invoke_text(system_prompt=system_prompt, user_prompt=user_prompt)

    def _user_by_id(self, user_id: int, *, users):
        for user in users:
            if user.id == user_id:
                return user
        raise RuntimeError(f"User '{user_id}' not found in AgentContext.users")

    def _validate_settings(self) -> None:
        required = ("toxicity_threshold", "moderation_time_span", "moderation_action_type")
        missing = [name for name in required if name not in self.settings]
        if missing:
            raise ValueError(f"Moderator settings missing required fields: {missing}")
        threshold = float(self.settings["toxicity_threshold"])
        if threshold < 0 or threshold > 1:
            raise ValueError("toxicity_threshold must be in [0, 1]")
        time_span = int(self.settings["moderation_time_span"])
        if time_span <= 0:
            raise ValueError("moderation_time_span must be > 0")
        strategy = str(self.settings["moderation_action_type"])
        if strategy not in {"one-fits-all", "personalized"}:
            raise ValueError("moderation_action_type must be 'one-fits-all' or 'personalized'")
        if strategy == "personalized" and (self.llm is None or not self.llm.is_available):
            raise ValueError("moderation_action_type 'personalized' requires a configured LangChain LLM model")
