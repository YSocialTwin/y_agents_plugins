from __future__ import annotations

from y_agents_plugins.database import ExperimentDatabase
from y_agents_plugins.models import AgentAction, AgentContext, AgentSpec


class ActionExecutor:
    """Persist plugin actions into the existing YSocial experiment tables."""

    def __init__(self, database: ExperimentDatabase):
        self.database = database

    def execute(
        self,
        connection,
        *,
        context: AgentContext,
        agent: AgentSpec,
        action: AgentAction,
    ) -> None:
        if action.action_type == "CREATE_POST":
            text = str(action.payload["text"])
            self.database.create_post(
                connection,
                username=agent.username,
                text=text,
                round_id=context.current_round.id,
            )
