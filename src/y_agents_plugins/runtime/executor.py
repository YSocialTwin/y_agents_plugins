from __future__ import annotations

from typing import Any

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec
from y_agents_plugins.db import ExperimentDatabase
from y_agents_plugins.stress_reward import StressRewardSystem, deep_update


class ActionExecutor:
    """Persist plugin actions into the existing YSocial experiment tables."""

    _UNTRACKED_PLUGIN_USER_TYPES = {
        "hello_world",
        "moderator",
        "propaganda",
        "master_of_puppets",
        "mop_puppet",
        "stress_attacker",
        "comic_relief",
    }

    def __init__(
        self,
        database: ExperimentDatabase,
        *,
        stress_reward_config: dict[str, Any] | None = None,
    ):
        self.database = database
        self.stress_reward_config = dict(stress_reward_config or {})
        self.stress_reward_enabled = bool(self.stress_reward_config.get("enabled", False))
        self.stress_reward_backward_rounds = int(
            self.stress_reward_config.get("backward_rounds", 24) or 24
        )
        self.stress_reward_system = StressRewardSystem(
            deep_update({}, self.stress_reward_config.get("system") or {})
        )

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
            self._apply_stress_reward_create_post(
                connection,
                context=context,
                action=action,
            )
        elif action.action_type == "CREATE_COMMENT":
            comment_id = self.database.create_comment(
                connection,
                username=actor_username,
                text=str(action.payload["text"]),
                round_id=context.current_round.id,
                parent_post_id=action.payload["parent_post_id"],
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
            self._apply_stress_reward_comment(
                connection,
                context=context,
                action=action,
            )
        elif action.action_type == "APPLY_MODERATION":
            round_id = action.payload.get("round_id", context.current_round.id)
            target_user_id = action.payload["target_user_id"]
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
                parent_post_id=action.payload["post_id"],
                is_moderation_comment=True,
            )
            self.database.mark_post_moderated(
                connection,
                post_id=action.payload["post_id"],
            )
            self.database.insert_moderation_event(
                connection,
                moderator_username=agent.username,
                moderated_post_id=action.payload["post_id"],
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
            self._apply_stress_reward_moderation(
                connection,
                context=context,
                action=action,
                target_user_id=target_user_id,
            )
        elif action.action_type == "FOLLOW_USER":
            created = self.database.create_follow(
                connection,
                username=actor_username,
                target_user_id=action.payload["target_user_id"],
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
                post_id=action.payload["post_id"],
                reaction_type=str(action.payload.get("reaction_type") or "like"),
                round_id=context.current_round.id,
            )
            self._persist_mop_activity(
                connection,
                actor_username=actor_username,
                created_post_id=action.payload["post_id"],
                action=action,
                round_id=context.current_round.id,
                status="executed" if reaction_id is not None else "skipped",
            )
            if reaction_id is not None:
                self._apply_stress_reward_reaction(
                    connection,
                    context=context,
                    action=action,
                )
        elif action.action_type == "REPORT_POST":
            reports_written = self.database.create_report(
                connection,
                username=actor_username,
                post_id=action.payload["post_id"],
                round_id=context.current_round.id,
                report_type=str(action.payload.get("report_type") or "synthetic_pressure"),
                count=max(1, int(action.payload.get("source_count", 1) or 1)),
            )
            self._persist_activity_log(
                connection,
                actor_username=actor_username,
                action_type=str(action.payload.get("action_name") or "report_post"),
                target_post_id=action.payload["post_id"],
                round_id=context.current_round.id,
                status="executed" if reports_written > 0 else "skipped",
                details={
                    "target_user_id": action.payload.get("target_user_id"),
                    "source_count": action.payload.get("source_count", 1),
                },
            )
        elif action.action_type == "SHARE_POST":
            share_id = self.database.create_share(
                connection,
                username=actor_username,
                shared_post_id=action.payload["post_id"],
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
            self._apply_stress_reward_share(
                connection,
                context=context,
                action=action,
            )
        elif action.action_type == "APPLY_STRESS_EVENT":
            self._apply_synthetic_stress_event(
                connection,
                context=context,
                action=action,
            )
            self._persist_activity_log(
                connection,
                actor_username=actor_username,
                action_type=str(action.payload.get("action_name") or "apply_stress_event"),
                target_post_id=(
                    action.payload["target_post_id"]
                    if action.payload.get("target_post_id") not in (None, "")
                    else None
                ),
                round_id=context.current_round.id,
                details={
                    "target_user_id": action.payload.get("target_user_id"),
                    "family": action.payload.get("family"),
                    "subtype": action.payload.get("subtype"),
                    "source_count": action.payload.get("source_count", 1),
                },
            )

    def _persist_propaganda_activity(
        self,
        connection,
        *,
        agent: AgentSpec,
        created_post_id: Any,
        action: AgentAction,
    ) -> None:
        activity = action.payload.get("propaganda_activity")
        if not isinstance(activity, dict):
            return
        propaganda_agent_uid = self.database.get_user_id(connection, agent.username)
        thread_id = activity.get("thread_id") or created_post_id
        self.database.insert_propaganda_activity(
            connection,
            target_uid=activity["target_uid"],
            propaganda_agent_uid=propaganda_agent_uid,
            thread_id=thread_id,
            discussion_round_id=activity["discussion_round_id"],
            target_opinion=activity.get("target_opinion"),
            topic_id=int(activity["topic_id"]),
        )

    def _persist_mop_activity(
        self,
        connection,
        *,
        actor_username: str,
        created_post_id: Any | None,
        action: AgentAction,
        round_id: Any,
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
                .where(schedules.c.id == schedule_id)
                .values(status=str(status), executed_round_id=round_id)
            )
        if self.database.has_table(connection, "activity_logs"):
            logs = self.database.table("activity_logs")
            actor_id = self.database.get_user_id(connection, actor_username)
            details = dict(activity.get("details") or {})
            if created_post_id is not None:
                details.setdefault("created_post_id", created_post_id)
            log_round_id = self.database._round_ordinal_for_id(connection, round_id)
            connection.execute(
                logs.insert().values(
                    p_id=actor_id,
                    action_type=str(activity.get("action_type") or action.action_type.lower()),
                    target_post_id=(
                        activity["target_post_id"]
                        if activity.get("target_post_id") not in (None, "")
                        else (
                            created_post_id
                            if created_post_id is not None and action.action_type in {"CREATE_POST", "CREATE_COMMENT", "SHARE_POST"}
                            else None
                        )
                    ),
                    status=str(status),
                    round_id=log_round_id,
                    details=str(details),
                )
            )
        connection.commit()

    def _persist_activity_log(
        self,
        connection,
        *,
        actor_username: str,
        action_type: str,
        round_id: Any,
        target_post_id: Any | None = None,
        status: str = "executed",
        details: dict[str, Any] | None = None,
    ) -> None:
        if not self.database.has_table(connection, "activity_logs"):
            return
        logs = self.database.table("activity_logs")
        actor_id = self.database.get_user_id(connection, actor_username)
        log_round_id = self.database._round_ordinal_for_id(connection, round_id)
        connection.execute(
            logs.insert().values(
                p_id=actor_id,
                action_type=str(action_type),
                target_post_id=target_post_id if target_post_id not in (None, "") else None,
                status=str(status),
                round_id=log_round_id,
                details=str(dict(details or {})),
            )
        )
        connection.commit()

    def _apply_stress_reward_create_post(
        self,
        connection,
        *,
        context: AgentContext,
        action: AgentAction,
    ) -> None:
        target_user_id = self._target_user_id_for_post_action(action)
        if target_user_id is None or not self._is_tracked_stress_reward_target(connection, target_user_id):
            return
        stress_reward_meta = action.payload.get("stress_reward") or {}
        tone = str(stress_reward_meta.get("tone") or "positive").strip().lower()
        if tone not in {"positive", "neutral", "critical", "hostile", "supportive"}:
            tone = "positive"
        state = self._current_stress_reward_state(
            connection, user_id=target_user_id, round_id=context.current_round.id
        )
        deltas = self.stress_reward_system.compute_comment_delta(
            tone=tone,
            current_stress=state["stress"],
            current_reward=state["reward"],
            directness=float(stress_reward_meta.get("directness", 1.0) or 1.0),
            public_exposure=float(stress_reward_meta.get("public_exposure", 1.0) or 1.0),
            support_strength=float(stress_reward_meta.get("support_strength", 1.0) or 1.0),
        )
        self._persist_stress_reward_variations(
            connection,
            target_user_id=target_user_id,
            current_round_id=context.current_round.id,
            deltas=deltas,
            action_name=str(stress_reward_meta.get("action") or f"post:{tone}"),
        )

    def _apply_stress_reward_comment(
        self,
        connection,
        *,
        context: AgentContext,
        action: AgentAction,
    ) -> None:
        target_user_id = self.database.get_post_author_id(
            connection, action.payload["parent_post_id"]
        )
        if not self._is_tracked_stress_reward_target(connection, target_user_id):
            return
        stress_reward_meta = action.payload.get("stress_reward") or {}
        tone = str(stress_reward_meta.get("tone") or "positive").strip().lower()
        if tone not in {"positive", "neutral", "critical", "hostile", "supportive"}:
            tone = "positive"
        state = self._current_stress_reward_state(
            connection, user_id=target_user_id, round_id=context.current_round.id
        )
        deltas = self.stress_reward_system.compute_comment_delta(
            tone=tone,
            current_stress=state["stress"],
            current_reward=state["reward"],
            directness=float(stress_reward_meta.get("directness", 1.0) or 1.0),
            public_exposure=self._resolved_comment_public_exposure(
                connection,
                stress_reward_meta=stress_reward_meta,
                reference_post_id=action.payload["parent_post_id"],
            ),
            support_strength=float(stress_reward_meta.get("support_strength", 1.0) or 1.0),
        )
        self._persist_stress_reward_variations(
            connection,
            target_user_id=target_user_id,
            current_round_id=context.current_round.id,
            deltas=deltas,
            action_name=str(stress_reward_meta.get("action") or f"comment:{tone}"),
        )

    def _apply_stress_reward_reaction(
        self,
        connection,
        *,
        context: AgentContext,
        action: AgentAction,
    ) -> None:
        target_user_id = self.database.get_post_author_id(connection, action.payload["post_id"])
        if not self._is_tracked_stress_reward_target(connection, target_user_id):
            return
        reaction = str(action.payload.get("reaction_type") or "like").strip().lower()
        if reaction not in {"like", "dislike"}:
            reaction = "like" if reaction in {"love", "laugh"} else "dislike"
        state = self._current_stress_reward_state(
            connection, user_id=target_user_id, round_id=context.current_round.id
        )
        deltas = self.stress_reward_system.compute_reaction_delta(
            reaction=reaction,
            current_stress=state["stress"],
            current_reward=state["reward"],
        )
        self._persist_stress_reward_variations(
            connection,
            target_user_id=target_user_id,
            current_round_id=context.current_round.id,
            deltas=deltas,
            action_name=f"reaction:{reaction}",
        )

    def _apply_stress_reward_share(
        self,
        connection,
        *,
        context: AgentContext,
        action: AgentAction,
    ) -> None:
        target_user_id = self.database.get_post_author_id(connection, action.payload["post_id"])
        if not self._is_tracked_stress_reward_target(connection, target_user_id):
            return
        stress_reward_meta = action.payload.get("stress_reward") or {}
        tone = str(stress_reward_meta.get("tone") or "positive").strip().lower()
        if tone not in {"positive", "hostile"}:
            tone = "positive"
        state = self._current_stress_reward_state(
            connection, user_id=target_user_id, round_id=context.current_round.id
        )
        deltas = self.stress_reward_system.compute_share_delta(
            tone=tone,
            current_stress=state["stress"],
            current_reward=state["reward"],
            public_exposure=float(stress_reward_meta.get("public_exposure", 1.0) or 1.0),
        )
        self._persist_stress_reward_variations(
            connection,
            target_user_id=target_user_id,
            current_round_id=context.current_round.id,
            deltas=deltas,
            action_name=str(stress_reward_meta.get("action") or f"share:{tone}"),
        )

    def _apply_stress_reward_moderation(
        self,
        connection,
        *,
        context: AgentContext,
        action: AgentAction,
        target_user_id: Any,
    ) -> None:
        if not self._is_tracked_stress_reward_target(connection, target_user_id):
            return
        stress_reward_meta = action.payload.get("stress_reward") or {}
        outcome = str(stress_reward_meta.get("outcome") or "sanctioned").strip().lower()
        if outcome not in {"protected", "sanctioned"}:
            outcome = "sanctioned"
        state = self._current_stress_reward_state(
            connection, user_id=target_user_id, round_id=context.current_round.id
        )
        deltas = self.stress_reward_system.compute_moderation_delta(
            outcome=outcome,
            current_stress=state["stress"],
            current_reward=state["reward"],
            support_strength=float(stress_reward_meta.get("support_strength", 1.0) or 1.0),
        )
        self._persist_stress_reward_variations(
            connection,
            target_user_id=target_user_id,
            current_round_id=context.current_round.id,
            deltas=deltas,
            action_name=str(stress_reward_meta.get("action") or f"moderation:{outcome}"),
        )

    def _apply_synthetic_stress_event(
        self,
        connection,
        *,
        context: AgentContext,
        action: AgentAction,
    ) -> None:
        target_user_id = action.payload.get("target_user_id")
        if target_user_id in (None, ""):
            return
        if not self._is_tracked_stress_reward_target(connection, target_user_id):
            return
        family = str(action.payload.get("family") or "").strip().lower()
        subtype = str(action.payload.get("subtype") or "").strip().lower()
        state = self._current_stress_reward_state(
            connection, user_id=target_user_id, round_id=context.current_round.id
        )
        volume = max(1, int(action.payload.get("volume", 1) or 1))
        importance = float(action.payload.get("importance", 1.0) or 1.0)
        public_exposure = float(action.payload.get("public_exposure", 1.0) or 1.0)
        directness = float(action.payload.get("directness", 1.0) or 1.0)
        support_strength = float(action.payload.get("support_strength", 1.0) or 1.0)

        if family == "reaction":
            deltas = self.stress_reward_system.compute_reaction_delta(
                reaction=subtype,
                current_stress=state["stress"],
                current_reward=state["reward"],
                importance=importance,
                volume=volume,
            )
        elif family == "comment":
            deltas = self.stress_reward_system.compute_comment_delta(
                tone=subtype,
                current_stress=state["stress"],
                current_reward=state["reward"],
                importance=importance,
                public_exposure=self._resolved_synthetic_comment_public_exposure(
                    connection,
                    action=action,
                    default_exposure=public_exposure,
                ),
                directness=directness,
                support_strength=support_strength,
            )
        elif family == "report":
            deltas = self.stress_reward_system.compute_report_delta(
                outcome=subtype,
                current_stress=state["stress"],
                current_reward=state["reward"],
                importance=importance,
                public_exposure=public_exposure,
                volume=volume,
            )
        elif family == "moderation":
            deltas = self.stress_reward_system.compute_moderation_delta(
                outcome=subtype,
                current_stress=state["stress"],
                current_reward=state["reward"],
                importance=importance,
                support_strength=support_strength,
            )
        else:
            raise ValueError(f"Unsupported synthetic stress event family: {family}")

        self._persist_stress_reward_variations(
            connection,
            target_user_id=target_user_id,
            current_round_id=context.current_round.id,
            deltas=deltas,
            action_name=str(action.payload.get("action_name") or f"{family}:{subtype}"),
        )

    def _resolved_comment_public_exposure(
        self,
        connection,
        *,
        stress_reward_meta: dict[str, Any],
        reference_post_id: Any,
    ) -> float:
        explicit = stress_reward_meta.get("public_exposure")
        if explicit not in (None, ""):
            return float(explicit)
        return self._infer_public_exposure_for_post(connection, post_id=reference_post_id)

    def _resolved_synthetic_comment_public_exposure(
        self,
        connection,
        *,
        action: AgentAction,
        default_exposure: float,
    ) -> float:
        if action.payload.get("public_exposure") not in (None, ""):
            return float(action.payload["public_exposure"])
        reference_post_id = action.payload.get("source_post_id") or action.payload.get("target_post_id")
        if reference_post_id in (None, ""):
            return float(default_exposure)
        return self._infer_public_exposure_for_post(connection, post_id=reference_post_id)

    def _infer_public_exposure_for_post(self, connection, *, post_id: Any) -> float:
        thread_size = max(1, int(self.database.get_thread_post_count_for_post(connection, post_id=post_id)))
        return min(2.0, 1.0 + 0.10 * max(0, thread_size - 1))

    def _current_stress_reward_state(
        self,
        connection,
        *,
        user_id: Any,
        round_id: Any,
    ) -> dict[str, float]:
        if not self.stress_reward_enabled:
            return {"stress": 0.0, "reward": 0.0}
        return self.database.get_current_stress_reward(
            connection,
            user_id=user_id,
            current_round_id=round_id,
            backward_rounds=self.stress_reward_backward_rounds,
        )

    def _persist_stress_reward_variations(
        self,
        connection,
        *,
        target_user_id: Any,
        current_round_id: Any,
        deltas: dict[str, Any],
        action_name: str,
    ) -> None:
        if not self.stress_reward_enabled or not self._is_tracked_stress_reward_target(connection, target_user_id):
            return
        variations = []
        delta_stress = float(deltas.get("delta_stress", 0.0))
        delta_reward = float(deltas.get("delta_reward", 0.0))
        if abs(delta_stress) > 1e-12:
            variations.append({"variable": "stress", "value": delta_stress})
        if abs(delta_reward) > 1e-12:
            variations.append({"variable": "reward", "value": delta_reward})
        if not variations:
            return
        self.database.set_stress_reward_variations(
            connection,
            user_id=target_user_id,
            round_id=current_round_id,
            variations=variations,
            action_name=action_name,
            aggregate_state={
                "stress": float(deltas.get("projected_stress", 0.0)),
                "reward": float(deltas.get("projected_reward", 0.0)),
            },
        )

    def _target_user_id_for_post_action(self, action: AgentAction) -> Any | None:
        stress_reward_meta = action.payload.get("stress_reward") or {}
        target_user_id = stress_reward_meta.get("target_user_id")
        if target_user_id not in (None, ""):
            return target_user_id
        propaganda_activity = action.payload.get("propaganda_activity") or {}
        target_user_id = propaganda_activity.get("target_uid")
        if target_user_id not in (None, ""):
            return target_user_id
        mop_activity = action.payload.get("mop_activity") or {}
        details = mop_activity.get("details") or {}
        target_user_id = details.get("target_user_id")
        if target_user_id not in (None, ""):
            return target_user_id
        return None

    def _is_tracked_stress_reward_target(self, connection, user_id: Any) -> bool:
        if not self.stress_reward_enabled:
            return False
        user_type = (self.database.get_user_type(connection, user_id) or "").strip().lower()
        return user_type not in self._UNTRACKED_PLUGIN_USER_TYPES

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
