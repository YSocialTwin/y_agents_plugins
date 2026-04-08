from __future__ import annotations

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec
from y_agents_plugins.db import ExperimentDatabase


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
        elif action.action_type == "APPLY_MODERATION":
            system_message_id = self.database.create_system_message(
                connection,
                message_type=str(action.payload["message_type"]),
                to_user_id=int(action.payload["target_user_id"]),
                message=str(action.payload["system_message_text"]),
                from_round=int(action.payload.get("round_id", context.current_round.id)),
                duration=int(action.payload["message_duration"]),
            )
            moderation_comment_id = self.database.create_comment(
                connection,
                username=agent.username,
                text=str(action.payload["system_message_text"]),
                round_id=int(action.payload.get("round_id", context.current_round.id)),
                parent_post_id=int(action.payload["post_id"]),
                is_moderation_comment=True,
            )
            self.database.mark_post_moderated(
                connection,
                post_id=int(action.payload["post_id"]),
            )
            self.database.insert_moderation_event(
                connection,
                moderator_username=agent.username,
                moderated_post_id=int(action.payload["post_id"]),
                moderation_type=str(action.payload["reason"]),
                round_id=int(action.payload.get("round_id", context.current_round.id)),
                generated_comment_id=moderation_comment_id,
            )
