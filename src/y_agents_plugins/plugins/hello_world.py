from __future__ import annotations

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec
from y_agents_plugins.plugins.base import BaseAgentPlugin


class HelloWorldAgent(BaseAgentPlugin):
    """Simple agent that posts a configured literal text once every active round."""

    agent_type = "hello_world"

    def on_tick(self, context: AgentContext, agent: AgentSpec) -> list[AgentAction]:
        message = str(
            (agent.parameters or {}).get("post_text")
            or self.settings.get("post_text")
            or "HELLO WORLD"
        )
        return [
            AgentAction(
                agent_type=self.agent_type,
                action_type="CREATE_POST",
                payload={
                    "text": message,
                    "agent_username": agent.username,
                    "round_id": context.current_round.id,
                },
            )
        ]
