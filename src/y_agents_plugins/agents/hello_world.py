from __future__ import annotations

from y_agents_plugins.agents.base import BaseAgentPlugin
from y_agents_plugins.models import AgentAction, AgentContext, AgentSpec


class HelloWorldAgent(BaseAgentPlugin):
    """Simple agent that posts HELLO WORLD once every simulation hour."""

    agent_type = "hello_world"

    def on_tick(self, context: AgentContext, agent: AgentSpec) -> list[AgentAction]:
        return [
            AgentAction(
                agent_type=self.agent_type,
                action_type="CREATE_POST",
                payload={
                    "text": "HELLO WORLD",
                    "agent_username": agent.username,
                    "round_id": context.current_round.id,
                },
            )
        ]
