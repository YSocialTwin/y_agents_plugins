from __future__ import annotations

from y_agents_plugins.agents.base import BaseAgentPlugin
from y_agents_plugins.models import AgentAction, AgentContext, AgentSpec


class ModeratorAgent(BaseAgentPlugin):
    """Example moderator plugin with a restricted moderation-oriented action space."""

    agent_type = "moderator"

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
                return [
                    AgentAction(
                        agent_type=self.agent_type,
                        action_type="FLAG_POST",
                        payload={
                            "agent_username": agent.username,
                            "agent_name": agent.name,
                            "activity_profile": agent.activity_profile,
                            "daily_budget": agent.daily_budget,
                            "post_id": post.id,
                            "round_id": context.current_round.id,
                            "reason": "keyword_match",
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
                        "round_id": context.current_round.id,
                    },
            )
        ]
