from __future__ import annotations

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec
from y_agents_plugins.plugins.base import BaseAgentPlugin


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
