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
        actor_username = str(action.payload.get("acting_username") or agent.username)
        if action.action_type == "CREATE_POST":
            text = str(action.payload["text"])
            post_id = self.database.create_post(
                connection,
                username=actor_username,
                text=text,
                round_id=context.current_round.id,
                topic_ids=self._topic_ids_from_action(action),
            )
            self._persist_mop_activity(
                connection,
                actor_username=actor_username,
                created_post_id=post_id,
                action=action,
                round_id=context.current_round.id,
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
                username=actor_username,
                text=str(action.payload["text"]),
                round_id=context.current_round.id,
                parent_post_id=int(action.payload["parent_post_id"]),
                topic_ids=self._topic_ids_from_action(action),
            )
            self._persist_mop_activity(
                connection,
                actor_username=actor_username,
                created_post_id=comment_id,
                action=action,
                round_id=context.current_round.id,
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
        elif action.action_type == "FOLLOW_USER":
            created = self.database.create_follow(
                connection,
                username=actor_username,
                target_user_id=int(action.payload["target_user_id"]),
                round_id=context.current_round.id,
                action=str(action.payload.get("follow_action") or "follow"),
            )
            self._persist_mop_activity(
                connection,
                actor_username=actor_username,
                created_post_id=None,
                action=action,
                round_id=context.current_round.id,
                status="executed" if created else "skipped",
            )
        elif action.action_type == "REACT_POST":
            reaction_id = self.database.create_reaction(
                connection,
                username=actor_username,
                post_id=int(action.payload["post_id"]),
                reaction_type=str(action.payload.get("reaction_type") or "like"),
                round_id=context.current_round.id,
            )
            self._persist_mop_activity(
                connection,
                actor_username=actor_username,
                created_post_id=int(action.payload["post_id"]),
                action=action,
                round_id=context.current_round.id,
                status="executed" if reaction_id is not None else "skipped",
            )
        elif action.action_type == "SHARE_POST":
            share_id = self.database.create_share(
                connection,
                username=actor_username,
                shared_post_id=int(action.payload["post_id"]),
                text=str(action.payload.get("text") or ""),
                round_id=context.current_round.id,
                topic_ids=self._topic_ids_from_action(action),
            )
            self._persist_mop_activity(
                connection,
                actor_username=actor_username,
                created_post_id=share_id,
                action=action,
                round_id=context.current_round.id,
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

    def _persist_mop_activity(
        self,
        connection,
        *,
        actor_username: str,
        created_post_id: int | None,
        action: AgentAction,
        round_id: int,
        status: str = "executed",
    ) -> None:
        activity = action.payload.get("mop_activity")
        if not isinstance(activity, dict):
            return
        schedule_id = activity.get("schedule_id")
        if schedule_id is not None and self.database.has_table(connection, "daily_schedules"):
            schedules = self.database.table("daily_schedules")
            connection.execute(
                schedules.update()
                .where(schedules.c.id == int(schedule_id))
                .values(status=str(status), executed_round_id=int(round_id))
            )
        if self.database.has_table(connection, "activity_logs"):
            logs = self.database.table("activity_logs")
            actor_id = self.database.get_user_id(connection, actor_username)
            details = dict(activity.get("details") or {})
            if created_post_id is not None:
                details.setdefault("created_post_id", int(created_post_id))
            connection.execute(
                logs.insert().values(
                    p_id=int(actor_id),
                    action_type=str(activity.get("action_type") or action.action_type.lower()),
                    target_post_id=(
                        int(activity["target_post_id"])
                        if activity.get("target_post_id") not in (None, "")
                        else (
                            int(created_post_id)
                            if created_post_id is not None and action.action_type in {"CREATE_POST", "CREATE_COMMENT", "SHARE_POST"}
                            else None
                        )
                    ),
                    status=str(status),
                    round_id=int(round_id),
                    details=str(details),
                )
            )
        connection.commit()

    @staticmethod
    def _topic_ids_from_action(action: AgentAction) -> list[int]:
        explicit = action.payload.get("topic_ids")
        if isinstance(explicit, (list, tuple)):
            return [int(topic_id) for topic_id in explicit if topic_id not in (None, "")]
        activity = action.payload.get("propaganda_activity")
        if not isinstance(activity, dict):
            return []
        topic_id = activity.get("topic_id")
        if topic_id in (None, ""):
            return []
        return [int(topic_id)]
