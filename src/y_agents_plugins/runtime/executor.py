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
            post_id = self.database.create_post(
                connection,
                username=agent.username,
                text=text,
                round_id=context.current_round.id,
                topic_ids=self._topic_ids_from_action(action),
            )
            self._persist_propaganda_activity(
                connection,
                agent=agent,
                created_post_id=post_id,
                action=action,
            )
        elif action.action_type == "CREATE_COMMENT":
            comment_id = self.database.create_comment(
                connection,
                username=agent.username,
                text=str(action.payload["text"]),
                round_id=context.current_round.id,
                parent_post_id=int(action.payload["parent_post_id"]),
                topic_ids=self._topic_ids_from_action(action),
            )
            self._persist_propaganda_activity(
                connection,
                agent=agent,
                created_post_id=comment_id,
                action=action,
            )
        elif action.action_type == "APPLY_MODERATION":
            round_id = int(action.payload.get("round_id", context.current_round.id))
            target_user_id = int(action.payload["target_user_id"])
            system_message_id = self.database.create_system_message(
                connection,
                message_type=str(action.payload["message_type"]),
                to_user_id=target_user_id,
                message=str(action.payload["system_message_text"]),
                from_round=round_id,
                duration=int(action.payload["message_duration"]),
            )
            moderation_comment_id = self.database.create_comment(
                connection,
                username=agent.username,
                text=str(action.payload["system_message_text"]),
                round_id=round_id,
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
                round_id=round_id,
                generated_comment_id=moderation_comment_id,
            )
            if bool(action.payload.get("shadow_ban_applied")) and not self.database.user_has_active_shadow_ban(
                connection,
                user_id=target_user_id,
                current_round_id=round_id,
            ):
                self.database.create_shadow_ban(
                    connection,
                    user_id=target_user_id,
                    start_tid=round_id,
                    duration=int(action.payload.get("shadow_ban_duration", 0) or 0),
                )
            if bool(action.payload.get("ban_applied")) and not self.database.user_is_banned(
                connection,
                user_id=target_user_id,
            ):
                self.database.create_ban(
                    connection,
                    user_id=target_user_id,
                    round_id=round_id,
                )

    def _persist_propaganda_activity(
        self,
        connection,
        *,
        agent: AgentSpec,
        created_post_id: int,
        action: AgentAction,
    ) -> None:
        activity = action.payload.get("propaganda_activity")
        if not isinstance(activity, dict):
            return
        propaganda_agent_uid = self.database.get_user_id(connection, agent.username)
        thread_id = int(activity.get("thread_id") or created_post_id)
        self.database.insert_propaganda_activity(
            connection,
            target_uid=int(activity["target_uid"]),
            propaganda_agent_uid=propaganda_agent_uid,
            thread_id=thread_id,
            discussion_round_id=int(activity["discussion_round_id"]),
            target_opinion=activity.get("target_opinion"),
            topic_id=int(activity["topic_id"]),
        )

    @staticmethod
    def _topic_ids_from_action(action: AgentAction) -> list[int]:
        activity = action.payload.get("propaganda_activity")
        if not isinstance(activity, dict):
            return []
        topic_id = activity.get("topic_id")
        if topic_id in (None, ""):
            return []
        return [int(topic_id)]
