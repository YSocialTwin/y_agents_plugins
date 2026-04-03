from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, String, Table, Text

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec, PostRecord
from y_agents_plugins.plugins.base import BaseAgentPlugin


class ModeratorAgent(BaseAgentPlugin):
    """Example moderator plugin with a restricted moderation-oriented action space."""

    agent_type = "moderator"

    def setup_database(self, database, connection) -> None:
        metadata = MetaData()
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
        toxicity_keywords = tuple(
            word.lower()
            for word in agent.parameters.get(
                "toxicity_keywords",
                self.settings.get("toxicity_keywords", ["hate", "idiot", "stupid"]),
            )
        )
        for post in context.recent_posts:
            lowered = post.text.lower()
            if any(keyword in lowered for keyword in toxicity_keywords):
                payload = {
                    "agent_username": agent.username,
                    "agent_name": agent.name,
                    "activity_profile": agent.activity_profile,
                    "daily_budget": agent.daily_budget,
                    "post_id": post.id,
                    "round_id": context.current_round.id,
                    "reason": "keyword_match",
                }
                generated_comment_text = self._generate_moderation_comment(post=post, agent=agent)
                if generated_comment_text:
                    payload["generated_comment_text"] = generated_comment_text
                return [
                    AgentAction(
                        agent_type=self.agent_type,
                        action_type="FLAG_POST",
                        payload=payload,
                    )
                ]

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
                "strategy_key": "keyword_match",
                "description": "Flag content whose text matches the configured toxicity keywords.",
            }
        ]

    def _generate_moderation_comment(self, *, post: PostRecord, agent: AgentSpec) -> str | None:
        if not self.settings.get("generate_moderation_message"):
            return None
        if self.llm is None or not self.llm.is_available:
            return None
        system_prompt = (
            "You are a moderation assistant for a YSocial simulation. "
            "Write one short moderation reply that explains the intervention neutrally."
        )
        user_prompt = (
            f"Moderator: {agent.name}\n"
            f"Moderated post id: {post.id}\n"
            f"Post text: {post.text}\n"
            "Return a single concise moderation message."
        )
        return self.llm.invoke_text(system_prompt=system_prompt, user_prompt=user_prompt)
