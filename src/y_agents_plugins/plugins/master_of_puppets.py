from __future__ import annotations

import json
import random
import re
from typing import Any

from sqlalchemy import Boolean, Column, Integer, MetaData, Table, Text, select

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec, PostRecord, UserRecord
from y_agents_plugins.plugins.base import BaseAgentPlugin


class MasterOfPuppetsAgent(BaseAgentPlugin):
    """LLM orchestrator that plans and dispatches actions for puppet accounts."""

    agent_type = "master_of_puppets"
    _SAFETY_DIRECTIVE = (
        "Keep every message non-toxic, non-threatening, non-harassing, and socially plausible. "
        "Do not use insults, hate, slurs, threats, or overt spam language."
    )

    def setup_database(self, database, connection) -> None:
        super().setup_database(database, connection)
        metadata = MetaData()
        tables = (
            Table(
                "mop_registry",
                metadata,
                Column("mop_id", Integer, primary_key=True),
                Column("target_topics", Text, nullable=False),
                Column("target_sentiment", Text, nullable=True),
                Column("puppet_list", Text, nullable=False),
                Column("last_planned_day", Integer, nullable=True),
            ),
            Table(
                "puppet_registry",
                metadata,
                Column("p_id", Integer, primary_key=True),
                Column("parent_mop_id", Integer, nullable=False),
                Column("username", Text, nullable=False),
                Column("is_banned", Boolean, nullable=False, default=False),
                Column("creation_date", Integer, nullable=False),
            ),
            Table(
                "daily_schedules",
                metadata,
                Column("id", Integer, primary_key=True, autoincrement=True),
                Column("p_id", Integer, nullable=False),
                Column("timestamp", Integer, nullable=False),
                Column("action_type", Text, nullable=False),
                Column("payload", Text, nullable=True),
                Column("scheduled_time", Integer, nullable=False),
                Column("schedule_day", Integer, nullable=False),
                Column("status", Text, nullable=False, default="pending"),
                Column("executed_round_id", Integer, nullable=True),
            ),
            Table(
                "activity_logs",
                metadata,
                Column("id", Integer, primary_key=True, autoincrement=True),
                Column("p_id", Integer, nullable=False),
                Column("action_type", Text, nullable=False),
                Column("target_post_id", Integer, nullable=True),
                Column("status", Text, nullable=False),
                Column("round_id", Integer, nullable=False),
                Column("details", Text, nullable=True),
            ),
        )
        for table in tables:
            if not database.has_table(connection, table.name):
                table.create(connection, checkfirst=True)
        connection.commit()

    def on_tick(self, context: AgentContext, agent: AgentSpec) -> list[AgentAction]:
        settings = self._resolved_settings(agent)
        self._validate_settings(settings)
        if context.connection is None:
            return [self._read_action(context, agent)]

        mop_id = self.database.get_user_id(context.connection, agent.username)
        puppet_ids = self._ensure_active_puppets(
            context=context,
            agent=agent,
            mop_id=mop_id,
            settings=settings,
        )
        if not puppet_ids:
            return [self._read_action(context, agent)]
        users = self.database.get_users(context.connection)

        campaigns = self._campaigns(settings)
        campaigns = self._resolved_campaigns(context, campaigns)
        if not campaigns:
            return [self._read_action(context, agent)]
        self._ensure_puppet_campaign_opinions(
            context=context,
            puppet_ids=puppet_ids,
            campaigns=campaigns,
        )
        self._sync_registry(
            context=context,
            mop_id=mop_id,
            campaigns=campaigns,
            puppet_ids=puppet_ids,
        )
        self._plan_daily_schedules(
            context=context,
            agent=agent,
            mop_id=mop_id,
            puppet_ids=puppet_ids,
            settings=settings,
            campaigns=campaigns,
            users=users,
        )

        remaining_dispatch_budget = self._remaining_dispatch_budget(
            context=context,
            agent=agent,
            puppet_ids=puppet_ids,
        )
        actions: list[AgentAction] = [self._read_action(context, agent)]
        if remaining_dispatch_budget <= 0:
            return actions

        scheduled_actions = self._due_scheduled_actions(
            context=context,
            agent=agent,
            mop_id=mop_id,
            puppet_ids=puppet_ids,
            campaigns=campaigns,
            settings=settings,
            remaining_budget=remaining_dispatch_budget,
            users=users,
        )
        actions.extend(scheduled_actions)
        remaining_dispatch_budget -= max(0, len(scheduled_actions))
        return actions

    def _ensure_active_puppets(
        self,
        *,
        context: AgentContext,
        agent: AgentSpec,
        mop_id: int,
        settings: dict[str, Any],
    ) -> list[int]:
        registry = self.database.table("puppet_registry")
        user_mgmt = self.database.table("user_mgmt")
        select_columns = [registry.c.p_id, registry.c.username, registry.c.is_banned]
        has_left_on = "left_on" in user_mgmt.c
        if has_left_on:
            select_columns.append(user_mgmt.c.left_on)
        target_count = max(1, int(settings.get("puppet_count", 1) or 1))
        rows = context.connection.execute(
            select(*select_columns)
            .select_from(
                registry.outerjoin(user_mgmt, user_mgmt.c.id == registry.c.p_id)
            )
            .where(registry.c.parent_mop_id == int(mop_id))
            .order_by(registry.c.p_id.asc())
        ).all()
        active_ids: list[int] = []
        known_usernames = {str(user.username) for user in context.users}
        for row in rows:
            puppet_id = int(row[0])
            username = str(row[1])
            is_banned = bool(row[2])
            left_on = row[3] if has_left_on and len(row) > 3 else None
            if left_on is not None:
                is_banned = True
            if is_banned:
                context.connection.execute(
                    registry.update()
                    .where(registry.c.p_id == puppet_id)
                    .values(is_banned=True)
                )
                continue
            active_ids.append(puppet_id)
            known_usernames.add(username)

        while len(active_ids) < target_count:
            username = self._next_puppet_username(agent.username, existing_usernames=known_usernames)
            puppet_id = self.database.create_plugin_user(
                context.connection,
                username=username,
                email=f"{username}@ysocial.it",
                password=username,
                user_type="mop_puppet",
                owner=agent.username,
                joined_on=int(context.current_round.id),
                activity_profile=agent.activity_profile,
                daily_budget=float(
                    max(
                        1,
                        round(
                            float(agent.daily_budget)
                            / max(1, int(settings.get("puppet_count", 1) or 1))
                        ),
                    )
                ),
            )
            context.connection.execute(
                registry.insert().values(
                    p_id=int(puppet_id),
                    parent_mop_id=int(mop_id),
                    username=username,
                    is_banned=False,
                    creation_date=int(context.current_round.id),
                )
            )
            context.connection.commit()
            active_ids.append(int(puppet_id))
            known_usernames.add(username)
        return active_ids

    def _sync_registry(
        self,
        *,
        context: AgentContext,
        mop_id: int,
        campaigns: list[dict[str, Any]],
        puppet_ids: list[int],
    ) -> None:
        registry = self.database.table("mop_registry")
        target_topics = json.dumps(
            [campaign["topic_name"] for campaign in campaigns], ensure_ascii=False
        )
        target_sentiment = json.dumps(
            {
                campaign["topic_name"]: campaign.get("target_opinion_group") or ""
                for campaign in campaigns
            },
            ensure_ascii=False,
        )
        puppet_list = json.dumps([int(puppet_id) for puppet_id in puppet_ids])
        existing = context.connection.execute(
            select(registry.c.mop_id).where(registry.c.mop_id == int(mop_id)).limit(1)
        ).first()
        values = {
            "target_topics": target_topics,
            "target_sentiment": target_sentiment,
            "puppet_list": puppet_list,
        }
        if existing is None:
            values["mop_id"] = int(mop_id)
            values["last_planned_day"] = None
            context.connection.execute(registry.insert().values(**values))
        else:
            context.connection.execute(
                registry.update().where(registry.c.mop_id == int(mop_id)).values(**values)
            )
        context.connection.commit()

    def _plan_daily_schedules(
        self,
        *,
        context: AgentContext,
        agent: AgentSpec,
        mop_id: int,
        puppet_ids: list[int],
        settings: dict[str, Any],
        campaigns: list[dict[str, Any]],
        users: tuple[UserRecord, ...],
    ) -> None:
        registry = self.database.table("mop_registry")
        schedules = self.database.table("daily_schedules")
        existing = context.connection.execute(
            select(registry.c.last_planned_day)
            .where(registry.c.mop_id == int(mop_id))
            .limit(1)
        ).first()
        if existing is not None and existing[0] is not None and int(existing[0]) == int(context.current_round.day):
            return

        current_slot = int(context.current_round.slot)
        remaining_slots = list(range(current_slot, 24))
        planner_rng = random.Random(
            f"mop-plan:{agent.username}:{context.current_round.day}:{context.current_round.id}"
        )
        assignments = self._daily_action_assignments(
            agent=agent,
            puppet_ids=puppet_ids,
            settings=settings,
            planner_rng=planner_rng,
        )
        for puppet_id, action_type in assignments:
            if not remaining_slots:
                break
            slot = planner_rng.choice(remaining_slots)
            scheduled_round = int(context.current_round.id) + (slot - current_slot)
            payload = self._build_schedule_payload(
                context=context,
                agent=agent,
                puppet_id=int(puppet_id),
                action_type=action_type,
                campaigns=campaigns,
                settings=settings,
                planner_rng=planner_rng,
                users=users,
            )
            context.connection.execute(
                schedules.insert().values(
                    p_id=int(puppet_id),
                    timestamp=int(context.current_round.id),
                    action_type=action_type,
                    payload=json.dumps(payload, ensure_ascii=False),
                    scheduled_time=int(scheduled_round),
                    schedule_day=int(context.current_round.day),
                    status="pending",
                    executed_round_id=None,
                )
            )
        context.connection.execute(
            registry.update()
            .where(registry.c.mop_id == int(mop_id))
            .values(last_planned_day=int(context.current_round.day))
        )
        context.connection.commit()

    def _build_schedule_payload(
        self,
        *,
        context: AgentContext,
        agent: AgentSpec,
        puppet_id: int,
        action_type: str,
        campaigns: list[dict[str, Any]],
        settings: dict[str, Any],
        planner_rng: random.Random,
        users: tuple[UserRecord, ...],
    ) -> dict[str, Any]:
        campaign = planner_rng.choice(campaigns)
        if action_type == "post":
            target_user = self._select_post_target_user(
                context=context,
                puppet_id=puppet_id,
                campaign=campaign,
                planner_rng=planner_rng,
                users=users,
            )
            return {
                "campaign": campaign,
                "text": self._build_post_text(
                    agent=agent,
                    campaign=campaign,
                    puppet_id=puppet_id,
                    target_user=target_user,
                ),
                "topic_ids": [int(campaign["runtime_topic_id"])],
                "target_user_id": None if target_user is None else int(target_user.id),
            }
        if action_type == "expand":
            return {"campaign": campaign}
        if action_type == "boost":
            return {
                "campaign": campaign,
                "boost_lookback_hours": int(settings.get("boost_lookback_hours", 12) or 12),
            }
        return {}

    def _due_scheduled_actions(
        self,
        *,
        context: AgentContext,
        agent: AgentSpec,
        mop_id: int,
        puppet_ids: list[int],
        campaigns: list[dict[str, Any]],
        settings: dict[str, Any],
        remaining_budget: int,
        users: tuple[UserRecord, ...],
    ) -> list[AgentAction]:
        if remaining_budget <= 0:
            return []
        schedules = self.database.table("daily_schedules")
        rows = context.connection.execute(
            select(
                schedules.c.id,
                schedules.c.p_id,
                schedules.c.action_type,
                schedules.c.payload,
                schedules.c.scheduled_time,
            )
            .where(schedules.c.p_id.in_([int(puppet_id) for puppet_id in puppet_ids]))
            .where(schedules.c.status == "pending")
            .where(schedules.c.scheduled_time <= int(context.current_round.id))
            .order_by(schedules.c.scheduled_time.asc(), schedules.c.id.asc())
        ).all()
        actions: list[AgentAction] = []
        for row in rows:
            if remaining_budget <= 0:
                break
            schedule_id, puppet_id, action_type, payload_raw, _scheduled_time = row
            payload = json.loads(payload_raw or "{}")
            budget = self._scheduled_action_budget(
                context=context,
                puppet_id=int(puppet_id),
                action_type=str(action_type),
            )
            executed_today = self._executed_action_count_today(
                context=context,
                puppet_id=int(puppet_id),
                action_type=str(action_type),
            )
            if budget >= 0 and executed_today >= budget:
                self._mark_schedule_skipped(
                    context=context,
                    schedule_id=int(schedule_id),
                    puppet_id=int(puppet_id),
                    action_type=str(action_type),
                    reason="local_budget_exhausted",
                )
                continue
            puppet = self._safe_user_by_id(int(puppet_id), users=users)
            if puppet is None:
                self._mark_schedule_skipped(
                    context=context,
                    schedule_id=int(schedule_id),
                    puppet_id=int(puppet_id),
                    action_type=str(action_type),
                    reason="puppet_missing",
                )
                continue
            action = self._materialize_scheduled_action(
                context=context,
                agent=agent,
                mop_id=mop_id,
                puppet=puppet,
                campaigns=campaigns,
                action_type=str(action_type),
                payload=payload,
                schedule_id=int(schedule_id),
                puppet_ids=puppet_ids,
            )
            if action is None:
                self._mark_schedule_skipped(
                    context=context,
                    schedule_id=int(schedule_id),
                    puppet_id=int(puppet_id),
                    action_type=str(action_type),
                    reason="no_valid_target",
                )
                continue
            context.connection.execute(
                schedules.update()
                .where(schedules.c.id == int(schedule_id))
                .values(status="dispatched")
            )
            context.connection.commit()
            actions.append(action)
            remaining_budget -= 1
        return actions

    def _materialize_scheduled_action(
        self,
        *,
        context: AgentContext,
        agent: AgentSpec,
        mop_id: int,
        puppet: UserRecord,
        campaigns: list[dict[str, Any]],
        action_type: str,
        payload: dict[str, Any],
        schedule_id: int,
        puppet_ids: list[int],
    ) -> AgentAction | None:
        if action_type == "post":
            return AgentAction(
                agent_type=self.agent_type,
                action_type="CREATE_POST",
                payload={
                    "acting_username": puppet.username,
                    "text": str(payload.get("text") or ""),
                    "topic_ids": list(payload.get("topic_ids") or []),
                    "stress_reward": {
                        "tone": "positive",
                        "action": "post:positive",
                        "target_user_id": payload.get("target_user_id"),
                    },
                    "mop_activity": {
                        "schedule_id": int(schedule_id),
                        "action_type": "post",
                        "details": {
                            "campaign_topic_id": int((payload.get("campaign") or {}).get("runtime_topic_id", -1)),
                            "target_user_id": payload.get("target_user_id"),
                        },
                    },
                },
            )
        if action_type == "expand":
            target_user = self._pick_follow_target(
                context=context,
                puppet=puppet,
                mop_id=mop_id,
                puppet_ids=puppet_ids,
            )
            if target_user is None:
                return None
            return AgentAction(
                agent_type=self.agent_type,
                action_type="FOLLOW_USER",
                payload={
                    "acting_username": puppet.username,
                    "target_user_id": int(target_user.id),
                    "follow_action": "follow",
                    "mop_activity": {
                        "schedule_id": int(schedule_id),
                        "action_type": "expand",
                        "details": {"target_user_id": int(target_user.id)},
                    },
                },
            )
        if action_type == "boost":
            sibling_post = self._pick_sibling_post_for_boost(
                context=context,
                puppet=puppet,
                puppet_ids=puppet_ids,
                lookback_hours=int(payload.get("boost_lookback_hours") or 12),
            )
            if sibling_post is None:
                return None
            if random.random() < 0.5:
                return AgentAction(
                    agent_type=self.agent_type,
                    action_type="REACT_POST",
                    payload={
                        "acting_username": puppet.username,
                        "post_id": int(sibling_post.id),
                        "reaction_type": "like",
                        "stress_reward": {
                            "action": "reaction:like",
                        },
                        "mop_activity": {
                            "schedule_id": int(schedule_id),
                            "action_type": "boost",
                            "target_post_id": int(sibling_post.id),
                            "details": {"boost_mode": "like"},
                        },
                    },
                )
            campaign = self._infer_campaign_for_post(campaigns=campaigns, post=sibling_post)
            return AgentAction(
                agent_type=self.agent_type,
                action_type="SHARE_POST",
                payload={
                    "acting_username": puppet.username,
                    "post_id": int(sibling_post.id),
                    "text": str(sibling_post.text),
                    "topic_ids": [int(campaign["runtime_topic_id"])],
                    "stress_reward": {
                        "tone": "positive",
                        "action": "share:positive",
                    },
                    "mop_activity": {
                        "schedule_id": int(schedule_id),
                        "action_type": "boost",
                        "target_post_id": int(sibling_post.id),
                        "details": {"boost_mode": "share"},
                    },
                },
            )
        return None

    def _pick_follow_target(
        self,
        *,
        context: AgentContext,
        puppet: UserRecord,
        mop_id: int,
        puppet_ids: list[int],
    ) -> UserRecord | None:
        followed = self.database.get_followed_user_ids(
            context.connection,
            username=puppet.username,
        )
        forbidden = {int(mop_id), int(puppet.id), *[int(puppet_id) for puppet_id in puppet_ids]}
        candidates = [
            user
            for user in context.users
            if int(user.id) not in forbidden
            and int(user.id) not in followed
            and not self.database.user_is_banned(context.connection, user_id=int(user.id))
        ]
        if not candidates:
            return None
        return random.choice(candidates)

    def _pick_sibling_post_for_boost(
        self,
        *,
        context: AgentContext,
        puppet: UserRecord,
        puppet_ids: list[int],
        lookback_hours: int,
    ) -> PostRecord | None:
        sibling_ids = [int(puppet_id) for puppet_id in puppet_ids if int(puppet_id) != int(puppet.id)]
        posts = self.database.get_posts_by_author_ids_since_round(
            context.connection,
            author_ids=sibling_ids,
            min_round_id=max(0, int(context.current_round.id) - max(1, int(lookback_hours))),
            limit=100,
        )
        candidates = [
            post
            for post in posts
            if int(post.author_id) != int(puppet.id)
            and int(post.is_moderation_comment or 0) == 0
        ]
        if not candidates:
            return None
        return random.choice(candidates)

    def _select_post_target_user(
        self,
        *,
        context: AgentContext,
        puppet_id: int,
        campaign: dict[str, Any],
        planner_rng: random.Random,
        users: tuple[UserRecord, ...],
    ) -> UserRecord | None:
        forbidden = {int(puppet_id)}
        candidates = [
            user
            for user in users
            if int(user.id) not in forbidden
            and str(user.user_type or "").strip().lower() not in {"mop_puppet", self.agent_type}
            and not self.database.user_is_banned(context.connection, user_id=int(user.id))
        ]
        if not candidates:
            return None
        if campaign.get("target_opinion") is not None and self.database.has_table(context.connection, "agent_opinion"):
            opinion_candidates = []
            for user in candidates:
                current = self.database.get_latest_agent_opinion(
                    context.connection,
                    user_id=int(user.id),
                    topic_id=int(campaign["runtime_topic_id"]),
                    current_round_id=int(context.current_round.id),
                )
                if current is None:
                    continue
                distance = abs(float(current) - float(campaign["target_opinion"]))
                opinion_candidates.append((distance, user))
            if opinion_candidates:
                opinion_candidates.sort(key=lambda item: item[0], reverse=True)
                return opinion_candidates[0][1]
        return planner_rng.choice(candidates)

    def _build_post_text(
        self,
        *,
        agent: AgentSpec,
        campaign: dict[str, Any],
        puppet_id: int,
        target_user: UserRecord | None,
    ) -> str:
        mention = f"@{target_user.username} " if target_user is not None else ""
        target_stance = campaign.get("target_opinion_group") or "engagement"
        if self.llm is None or not getattr(self.llm, "is_available", False):
            return (
                f"{mention}I keep thinking about {campaign['topic_name']}. "
                f"There is room for a more {target_stance.lower()} conversation about it."
            ).strip()
        system_prompt = (
            "You are the strategic planner behind a coordinated but human-like social campaign. "
            f"{self._SAFETY_DIRECTIVE} Write a short, plausible microblogging post."
        )
        override_prompt = str(self._resolved_settings(agent).get("llm_prompt_override") or "").strip()
        if override_prompt:
            system_prompt = override_prompt
        user_prompt = (
            f"Campaign topic: {campaign['topic_name']}\n"
            f"Desired stance: {target_stance}\n"
            f"Puppet id: {puppet_id}\n"
            f"Target user: {target_user.username if target_user else 'none'}\n"
            "Output one short post, no explanations."
        )
        text = self.llm.invoke_text(system_prompt=system_prompt, user_prompt=user_prompt).strip()
        return self._normalize_mention(text, target_user.username if target_user else None)

    @staticmethod
    def _normalize_mention(text: str, username: str | None) -> str:
        cleaned = str(text or "").strip()
        if not username:
            return cleaned
        if not re.search(rf"@{re.escape(username)}\b", cleaned, flags=re.IGNORECASE):
            cleaned = f"@{username} {cleaned}".strip()
        return cleaned

    def _mark_schedule_skipped(
        self,
        *,
        context: AgentContext,
        schedule_id: int,
        puppet_id: int,
        action_type: str,
        reason: str,
    ) -> None:
        schedules = self.database.table("daily_schedules")
        logs = self.database.table("activity_logs")
        context.connection.execute(
            schedules.update()
            .where(schedules.c.id == int(schedule_id))
            .values(status="skipped", executed_round_id=int(context.current_round.id))
        )
        context.connection.execute(
            logs.insert().values(
                p_id=int(puppet_id),
                action_type=str(action_type),
                target_post_id=None,
                status="skipped",
                round_id=int(context.current_round.id),
                details=str({"reason": reason, "schedule_id": int(schedule_id)}),
            )
        )
        context.connection.commit()

    def _remaining_dispatch_budget(
        self,
        *,
        context: AgentContext,
        agent: AgentSpec,
        puppet_ids: list[int],
    ) -> int:
        logs = self.database.table("activity_logs")
        row = context.connection.execute(
            select(logs.c.id)
            .where(logs.c.p_id.in_([int(puppet_id) for puppet_id in puppet_ids]))
            .where(logs.c.round_id >= (int(context.current_round.id) - int(context.current_round.slot)))
            .where(logs.c.status == "executed")
        ).all()
        used = len(row)
        return max(0, int(float(agent.daily_budget)) - used)

    def _executed_action_count_today(
        self,
        *,
        context: AgentContext,
        puppet_id: int,
        action_type: str,
    ) -> int:
        logs = self.database.table("activity_logs")
        return len(
            context.connection.execute(
                select(logs.c.id)
                .where(logs.c.p_id == int(puppet_id))
                .where(logs.c.action_type == str(action_type))
                .where(logs.c.round_id >= (int(context.current_round.id) - int(context.current_round.slot)))
                .where(logs.c.status == "executed")
            ).all()
        )

    def _scheduled_action_budget(
        self,
        *,
        context: AgentContext,
        puppet_id: int,
        action_type: str,
    ) -> int:
        schedules = self.database.table("daily_schedules")
        return len(
            context.connection.execute(
                select(schedules.c.id)
                .where(schedules.c.p_id == int(puppet_id))
                .where(schedules.c.action_type == str(action_type))
                .where(schedules.c.schedule_day == int(context.current_round.day))
            ).all()
        )

    def _daily_action_assignments(
        self,
        *,
        agent: AgentSpec,
        puppet_ids: list[int],
        settings: dict[str, Any],
        planner_rng: random.Random,
    ) -> list[tuple[int, str]]:
        total_budget = max(1, int(float(agent.daily_budget)))
        weights = {
            "post": max(0.0, float(settings.get("post_budget_percentage", 0) or 0.0)),
            "boost": max(0.0, float(settings.get("support_budget_percentage", 0) or 0.0)),
            "expand": max(0.0, float(settings.get("network_budget_percentage", 0) or 0.0)),
        }
        total_weight = sum(weights.values())
        if total_weight <= 0:
            return []
        allocations: dict[str, int] = {}
        fractional_parts: list[tuple[float, str]] = []
        allocated = 0
        for action_type, weight in weights.items():
            exact = (weight / total_weight) * total_budget
            base = int(exact)
            allocations[action_type] = base
            allocated += base
            fractional_parts.append((exact - base, action_type))
        for _fraction, action_type in sorted(fractional_parts, reverse=True):
            if allocated >= total_budget:
                break
            allocations[action_type] += 1
            allocated += 1
        assignments: list[tuple[int, str]] = []
        if not puppet_ids:
            return assignments
        puppet_cycle = list(puppet_ids)
        planner_rng.shuffle(puppet_cycle)
        idx = 0
        for action_type in ("post", "expand", "boost"):
            for _ in range(max(0, allocations.get(action_type, 0))):
                assignments.append((int(puppet_cycle[idx % len(puppet_cycle)]), action_type))
                idx += 1
        planner_rng.shuffle(assignments)
        return assignments

    def _ensure_puppet_campaign_opinions(
        self,
        *,
        context: AgentContext,
        puppet_ids: list[int],
        campaigns: list[dict[str, Any]],
    ) -> None:
        if not self.database.has_table(context.connection, "agent_opinion"):
            return
        for puppet_id in puppet_ids:
            for campaign in campaigns:
                target_opinion = campaign.get("target_opinion")
                if target_opinion is None:
                    continue
                self.database.set_fixed_agent_opinion(
                    context.connection,
                    user_id=int(puppet_id),
                    topic_id=int(campaign["runtime_topic_id"]),
                    opinion=float(target_opinion),
                    round_id=int(context.current_round.id),
                )

    def _resolved_campaigns(
        self,
        context: AgentContext,
        campaigns: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for campaign in campaigns:
            runtime_topic_id = self.database.resolve_interest_topic_id(
                context.connection,
                configured_topic_id=int(campaign["topic_id"]),
                topic_name=str(campaign["topic_name"]),
            )
            if runtime_topic_id is None:
                continue
            resolved_campaign = dict(campaign)
            resolved_campaign["runtime_topic_id"] = int(runtime_topic_id)
            resolved.append(resolved_campaign)
        return resolved

    def _campaigns(self, settings: dict[str, Any]) -> list[dict[str, Any]]:
        campaigns = settings.get("mop_campaigns") or []
        normalized: list[dict[str, Any]] = []
        for campaign in campaigns:
            if not isinstance(campaign, dict):
                continue
            topic_id = campaign.get("topic_id")
            if topic_id in (None, ""):
                continue
            normalized.append(
                {
                    "topic_id": int(topic_id),
                    "runtime_topic_id": int(topic_id),
                    "topic_name": str(campaign.get("topic_name") or topic_id),
                    "target_opinion": (
                        None
                        if campaign.get("target_opinion") in (None, "")
                        else float(campaign.get("target_opinion"))
                    ),
                    "target_opinion_group": str(campaign.get("target_opinion_group") or "").strip(),
                }
            )
        return normalized

    def _infer_campaign_for_post(
        self,
        *,
        campaigns: list[dict[str, Any]],
        post: PostRecord,
    ) -> dict[str, Any]:
        for campaign in campaigns:
            if campaign["topic_name"].lower() in str(post.text or "").lower():
                return campaign
        return campaigns[0]

    def _next_puppet_username(
        self,
        mop_username: str,
        *,
        existing_usernames: set[str],
    ) -> str:
        base = f"{mop_username}_puppet"
        index = 1
        while f"{base}_{index}" in existing_usernames:
            index += 1
        return f"{base}_{index}"

    def _resolved_settings(self, agent: AgentSpec | None = None) -> dict[str, Any]:
        settings = dict(self.settings)
        if agent is not None:
            settings.update(agent.parameters or {})
        return settings

    @staticmethod
    def _validate_settings(settings: dict[str, Any]) -> None:
        if max(1, int(settings.get("puppet_count", 1) or 1)) <= 0:
            raise ValueError("puppet_count must be positive")
        if not settings.get("mop_campaigns"):
            raise ValueError("mop_campaigns requires at least one configured topic")
        total_percentage = sum(
            max(0.0, float(settings.get(key, 0) or 0.0))
            for key in (
                "post_budget_percentage",
                "support_budget_percentage",
                "network_budget_percentage",
            )
        )
        if total_percentage <= 0:
            raise ValueError("MoP budget percentages must sum to a positive value")

    def _read_action(self, context: AgentContext, agent: AgentSpec) -> AgentAction:
        return AgentAction(
            agent_type=self.agent_type,
            action_type="READ",
            payload={
                "agent_username": agent.username,
                "agent_name": agent.name,
                "round_id": context.current_round.id,
            },
        )

    @staticmethod
    def _safe_user_by_id(
        user_id: int, *, users: tuple[UserRecord, ...]
    ) -> UserRecord | None:
        for user in users:
            if int(user.id) == int(user_id):
                return user
        return None
