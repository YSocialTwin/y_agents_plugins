from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Column,
    Integer,
    MetaData,
    REAL,
    String,
    Table,
    create_engine,
    func,
    inspect,
    literal,
    select,
    text,
    event,
)
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.pool import NullPool

from y_agents_plugins.core.models import AgentSpec, PostRecord, SimulationRound, UserRecord


class ExperimentDatabase:
    """SQLAlchemy gateway for experiment and plugin-owned tables."""

    def __init__(self, database_url: str | Path):
        self.database_url = self._normalize_database_url(database_url)
        engine_kwargs: dict[str, Any] = {
            "future": True,
            "pool_pre_ping": True,
            "poolclass": NullPool,
        }
        if self.database_url.startswith("sqlite:///"):
            engine_kwargs["connect_args"] = {"timeout": 30}
        self.engine: Engine = create_engine(
            self.database_url,
            **engine_kwargs,
        )
        if self.database_url.startswith("sqlite:///"):
            self._configure_sqlite_engine(self.engine)
        self.metadata = MetaData()
        self._reflected_tables: dict[str, Table] = {}
        self._validate_connectivity()

    def connect(self) -> Connection:
        return self.engine.connect()

    @staticmethod
    def _configure_sqlite_engine(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, connection_record):  # noqa: ARG001
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=30000")
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    def get_current_round(self, connection: Connection) -> SimulationRound:
        rounds = self.table("rounds")
        row = connection.execute(
            select(rounds.c.id, rounds.c.day, rounds.c.hour)
            .order_by(rounds.c.day.desc(), rounds.c.hour.desc(), rounds.c.id.desc())
            .limit(1)
        ).mappings().first()
        if row is None:
            raise RuntimeError("No rows found in rounds table")
        return self._round_from_row(row)

    def get_rounds_after(
        self,
        connection: Connection,
        after_round_id: Any | None,
    ) -> tuple[SimulationRound, ...]:
        rounds = self.table("rounds")
        statement = (
            select(rounds.c.id, rounds.c.day, rounds.c.hour)
            .order_by(rounds.c.day.asc(), rounds.c.hour.asc(), rounds.c.id.asc())
        )
        if after_round_id is None:
            rows = connection.execute(statement).mappings().all()
        else:
            after_row = connection.execute(
                select(rounds.c.id, rounds.c.day, rounds.c.hour)
                .where(rounds.c.id == after_round_id)
                .limit(1)
            ).mappings().first()
            if after_row is None:
                rows = connection.execute(statement).mappings().all()
            else:
                rows = connection.execute(
                    statement.where(
                        (rounds.c.day > int(after_row["day"]))
                        | (
                            (rounds.c.day == int(after_row["day"]))
                            & (rounds.c.hour > int(after_row["hour"]))
                        )
                        | (
                            (rounds.c.day == int(after_row["day"]))
                            & (rounds.c.hour == int(after_row["hour"]))
                            & (rounds.c.id > after_row["id"])
                        )
                    )
                ).mappings().all()
        return tuple(self._round_from_row(row) for row in rows)

    def get_recent_posts(
        self,
        connection: Connection,
        *,
        round_id: Any,
        limit: int,
    ) -> tuple[PostRecord, ...]:
        post = self.table("post")
        rounds = self.table("rounds")
        current_round = connection.execute(
            select(rounds.c.id, rounds.c.day, rounds.c.hour)
            .where(rounds.c.id == round_id)
            .limit(1)
        ).mappings().first()
        statement = select(
            post.c.id,
            post.c.user_id,
            post.c.tweet,
            post.c.round,
            rounds.c.day.label("round_day"),
            rounds.c.hour.label("round_hour"),
            post.c.comment_to,
            post.c.thread_id,
            post.c.shared_from,
            (post.c.moderated if "moderated" in post.c else literal(0)).label("moderated"),
            (
                post.c.is_moderation_comment
                if "is_moderation_comment" in post.c
                else literal(0)
            ).label("is_moderation_comment"),
            literal(0.0).label("toxicity"),
            literal(0).label("reported_count"),
        ).select_from(post.outerjoin(rounds, rounds.c.id == post.c.round))
        if current_round is not None:
            statement = statement.where(
                rounds.c.id.is_(None)
                | (rounds.c.day < int(current_round["day"]))
                | (
                    (rounds.c.day == int(current_round["day"]))
                    & (rounds.c.hour <= int(current_round["hour"]))
                )
            )

        if self.has_table(connection, "post_toxicity"):
            post_toxicity = self.table("post_toxicity")
            toxicity_columns = [
                post_toxicity.c[name]
                for name in (
                    "toxicity",
                    "severe_toxicity",
                    "identity_attack",
                    "insult",
                    "profanity",
                    "threat",
                    "sexually_explicit",
                    "flirtation",
                )
                if name in post_toxicity.c
            ]
            per_row_toxicity = self._max_score_expr(*toxicity_columns)
            toxicity_subquery = (
                select(
                    post_toxicity.c.post_id.label("post_id"),
                    func.max(per_row_toxicity).label("toxicity"),
                )
                .group_by(post_toxicity.c.post_id)
                .subquery()
            )
            statement = statement.outerjoin(toxicity_subquery, toxicity_subquery.c.post_id == post.c.id).with_only_columns(
                post.c.id,
                post.c.user_id,
                post.c.tweet,
                post.c.round,
                rounds.c.day.label("round_day"),
                rounds.c.hour.label("round_hour"),
                post.c.comment_to,
                post.c.thread_id,
                post.c.shared_from,
                (post.c.moderated if "moderated" in post.c else literal(0)).label("moderated"),
                (
                    post.c.is_moderation_comment
                    if "is_moderation_comment" in post.c
                    else literal(0)
                ).label("is_moderation_comment"),
                func.coalesce(toxicity_subquery.c.toxicity, 0.0).label("toxicity"),
                literal(0).label("reported_count"),
            )

        if self.has_table(connection, "reported"):
            reported = self.table("reported")
            reported_subquery = (
                select(
                    reported.c.to_post.label("post_id"),
                    func.count(reported.c.id).label("reported_count"),
                )
                .where(reported.c.to_post.is_not(None))
                .group_by(reported.c.to_post)
                .subquery()
            )
            statement = statement.outerjoin(reported_subquery, reported_subquery.c.post_id == post.c.id).with_only_columns(
                post.c.id,
                post.c.user_id,
                post.c.tweet,
                post.c.round,
                rounds.c.day.label("round_day"),
                rounds.c.hour.label("round_hour"),
                post.c.comment_to,
                post.c.thread_id,
                post.c.shared_from,
                (post.c.moderated if "moderated" in post.c else literal(0)).label("moderated"),
                statement.selected_columns.is_moderation_comment,
                statement.selected_columns.toxicity,
                func.coalesce(reported_subquery.c.reported_count, 0).label("reported_count"),
            )

        rows = connection.execute(
            statement.order_by(
                rounds.c.day.desc().nullslast(),
                rounds.c.hour.desc().nullslast(),
                post.c.id.desc(),
            ).limit(limit)
        ).mappings().all()
        return tuple(
            PostRecord(
                id=_raw_id(row["id"]),
                author_id=_raw_id(row["user_id"]),
                text=str(row["tweet"]),
                round_id=_raw_id(row["round"]),
                comment_to=_nullable_id(row["comment_to"]),
                thread_id=_nullable_id(row["thread_id"]),
                shared_from=_nullable_id(row["shared_from"]),
                round_day=int(row["round_day"]) if row["round_day"] is not None else None,
                round_slot=int(row["round_hour"]) if row["round_hour"] is not None else None,
                moderated=int(row["moderated"] or 0),
                is_moderation_comment=int(row["is_moderation_comment"] or 0),
                toxicity=float(row["toxicity"]) if row["toxicity"] is not None else None,
                reported_count=int(row["reported_count"] or 0),
            )
            for row in rows
        )

    def get_users(self, connection: Connection) -> tuple[UserRecord, ...]:
        user_mgmt = self.table("user_mgmt")
        rows = connection.execute(select(user_mgmt).order_by(user_mgmt.c.id.asc())).mappings().all()
        return tuple(
            UserRecord(
                id=_raw_id(row["id"]),
                username=str(row["username"]),
                user_type=row["user_type"],
                owner=row["owner"],
                profile={
                    key: value
                    for key, value in row.items()
                    if key not in {"id", "username", "user_type", "owner", "password"}
                },
            )
            for row in rows
        )

    def get_user_id(self, connection: Connection, username: str) -> Any:
        user_mgmt = self.table("user_mgmt")
        row = connection.execute(
            select(user_mgmt.c.id).where(user_mgmt.c.username == username).limit(1)
        ).first()
        if row is None:
            raise RuntimeError(f"User '{username}' not found in user_mgmt")
        return _raw_id(row[0])

    def register_agents(
        self,
        connection: Connection,
        agents: tuple[AgentSpec, ...],
        *,
        joined_on: Any,
    ) -> None:
        user_mgmt = self.table("user_mgmt")
        supported_columns = self._table_columns(connection, "user_mgmt")
        id_type = self._id_sql_type(connection)
        for agent in agents:
            existing = connection.execute(
                select(user_mgmt.c.id)
                .where((user_mgmt.c.username == agent.username) | (user_mgmt.c.email == agent.email))
                .limit(1)
            ).first()

            values = {
                "username": agent.username,
                "email": agent.email,
                "password": agent.password,
                "user_type": agent.agent_type,
                "leaning": agent.leaning,
                "interests": agent.interests,
                "age": agent.age,
                "oe": agent.oe,
                "co": agent.co,
                "ex": agent.ex,
                "ag": agent.ag,
                "ne": agent.ne,
                "recsys_type": agent.recsys_type,
                "language": agent.language,
                "owner": agent.owner,
                "education_level": agent.education_level,
                "joined_on": joined_on if agent.joined_on <= 0 else agent.joined_on,
                "frecsys_type": agent.frecsys_type,
                "activity_profile": agent.activity_profile,
                "daily_budget": agent.daily_budget,
            }
            filtered_values = {
                column: value
                for column, value in values.items()
                if column in supported_columns and value is not None
            }

            if existing is None:
                if "id" in supported_columns and id_type is not Integer:
                    filtered_values.setdefault("id", str(uuid.uuid4()))
                connection.execute(user_mgmt.insert().values(**filtered_values))
            else:
                connection.execute(
                    user_mgmt.update().where(user_mgmt.c.id == existing[0]).values(**filtered_values)
                )
        connection.commit()

    def create_post(
        self,
        connection: Connection,
        *,
        username: str,
        text: str,
        round_id: Any,
        topic_ids: list[int] | tuple[int, ...] | None = None,
    ) -> Any:
        post = self.table("post")
        user_id = self.get_user_id(connection, username)
        result = connection.execute(
            post.insert()
            .values(
                tweet=text,
                user_id=user_id,
                comment_to=-1,
                thread_id=None,
                round=round_id,
                shared_from=-1,
            )
            .returning(post.c.id)
        )
        post_id = _raw_id(result.scalar_one())
        if "thread_id" in post.c:
            connection.execute(
                post.update().where(post.c.id == post_id).values(thread_id=post_id)
            )
        self._insert_mentions_for_text(
            connection,
            text=text,
            post_id=post_id,
            round_id=round_id,
        )
        self._insert_post_topics(
            connection,
            post_id=post_id,
            topic_ids=topic_ids,
        )
        connection.commit()
        return post_id

    def create_comment(
        self,
        connection: Connection,
        *,
        username: str,
        text: str,
        round_id: Any,
        parent_post_id: Any,
        is_moderation_comment: bool = False,
        topic_ids: list[int] | tuple[int, ...] | None = None,
    ) -> Any:
        post = self.table("post")
        user_id = self.get_user_id(connection, username)
        parent = connection.execute(
            select(post.c.id, post.c.thread_id).where(post.c.id == parent_post_id).limit(1)
        ).mappings().first()
        if parent is None:
            raise RuntimeError(f"Parent post '{parent_post_id}' not found in post table")
        thread_id = _nullable_id(parent["thread_id"]) or _raw_id(parent["id"])
        values = {
            "tweet": text,
            "user_id": user_id,
            "comment_to": parent_post_id,
            "thread_id": thread_id,
            "round": round_id,
            "shared_from": -1,
        }
        if "is_moderation_comment" in post.c:
            values["is_moderation_comment"] = int(bool(is_moderation_comment))
        result = connection.execute(post.insert().values(**values).returning(post.c.id))
        comment_id = _raw_id(result.scalar_one())
        self._insert_mentions_for_text(
            connection,
            text=text,
            post_id=comment_id,
            round_id=round_id,
        )
        self._insert_post_topics(
            connection,
            post_id=comment_id,
            topic_ids=topic_ids,
        )
        connection.commit()
        return comment_id

    def create_share(
        self,
        connection: Connection,
        *,
        username: str,
        shared_post_id: Any,
        text: str,
        round_id: Any,
        topic_ids: list[int] | tuple[int, ...] | None = None,
    ) -> Any:
        post = self.table("post")
        user_id = self.get_user_id(connection, username)
        original = connection.execute(
            select(post).where(post.c.id == shared_post_id).limit(1)
        ).mappings().first()
        if original is None:
            raise RuntimeError(f"Shared post '{shared_post_id}' not found in post table")
        values: dict[str, Any] = {
            "tweet": str(text or original.get("tweet") or ""),
            "user_id": user_id,
            "comment_to": -1,
            "thread_id": None,
            "round": round_id,
            "shared_from": shared_post_id,
        }
        for optional_column in ("news_id", "image_id", "image_post_id"):
            if optional_column in post.c and optional_column in original:
                values[optional_column] = original[optional_column]
        result = connection.execute(post.insert().values(**values).returning(post.c.id))
        share_id = _raw_id(result.scalar_one())
        if "thread_id" in post.c:
            connection.execute(
                post.update().where(post.c.id == share_id).values(thread_id=share_id)
            )
        self._insert_mentions_for_text(
            connection,
            text=str(text or ""),
            post_id=share_id,
            round_id=round_id,
        )
        self._insert_post_topics(
            connection,
            post_id=share_id,
            topic_ids=topic_ids,
        )
        connection.commit()
        return share_id

    def create_reaction(
        self,
        connection: Connection,
        *,
        username: str,
        post_id: Any,
        reaction_type: str,
        round_id: Any,
    ) -> Any | None:
        if not self.has_table(connection, "reactions"):
            return None
        reactions = self.table("reactions")
        post = self.table("post")
        user_id = self.get_user_id(connection, username)
        result = connection.execute(
            reactions.insert()
            .values(
                round=round_id,
                user_id=user_id,
                post_id=post_id,
                type=str(reaction_type),
            )
            .returning(reactions.c.id)
        )
        reaction_id = _raw_id(result.scalar_one())
        if "reaction_count" in post.c:
            current = connection.execute(
                select(post.c.reaction_count).where(post.c.id == post_id).limit(1)
            ).first()
            if current is not None:
                connection.execute(
                    post.update()
                    .where(post.c.id == post_id)
                    .values(reaction_count=int(current[0] or 0) + 1)
                )
        connection.commit()
        return reaction_id

    def create_report(
        self,
        connection: Connection,
        *,
        username: str,
        post_id: Any,
        round_id: Any,
        report_type: str = "synthetic_pressure",
        count: int = 1,
    ) -> int:
        if not self.has_table(connection, "reported"):
            return 0
        reported = self.table("reported")
        user_id = self.get_user_id(connection, username)
        written = 0
        for _ in range(max(1, int(count))):
            connection.execute(
                reported.insert().values(
                    type=str(report_type),
                    to_uid=None,
                    to_post=post_id,
                    from_uid=user_id,
                    tid=round_id,
                )
            )
            written += 1
        if written:
            connection.commit()
        return written

    def create_follow(
        self,
        connection: Connection,
        *,
        username: str,
        target_user_id: Any,
        round_id: Any,
        action: str = "follow",
    ) -> bool:
        if not self.has_table(connection, "follow"):
            return False
        user_id = self.get_user_id(connection, username)
        if str(user_id) == str(target_user_id):
            return False
        follow = self.table("follow")
        existing = connection.execute(
            select(follow.c.id, follow.c.action)
            .where(follow.c.user_id == user_id)
            .where(follow.c.follower_id == target_user_id)
            .order_by(follow.c.round.desc(), follow.c.id.desc())
            .limit(1)
        ).first()
        normalized_action = str(action or "follow").strip().lower()
        if existing is not None and str(existing[1] or "").strip().lower() == normalized_action:
            return False
        if existing is None and normalized_action == "unfollow":
            return False
        connection.execute(
            follow.insert().values(
                user_id=user_id,
                follower_id=target_user_id,
                round=round_id,
                action=normalized_action,
            )
        )
        connection.commit()
        return True

    def create_plugin_user(
        self,
        connection: Connection,
        *,
        username: str,
        email: str,
        password: str,
        user_type: str,
        owner: str | None,
        joined_on: Any,
        activity_profile: str | None = None,
        daily_budget: float | None = None,
    ) -> Any:
        user_mgmt = self.table("user_mgmt")
        existing = connection.execute(
            select(user_mgmt.c.id).where(user_mgmt.c.username == str(username)).limit(1)
        ).first()
        supported_columns = self._table_columns(connection, "user_mgmt")
        id_type = self._id_sql_type(connection)
        values = {
            "username": str(username),
            "email": str(email),
            "password": str(password),
            "user_type": str(user_type),
            "owner": owner,
            "joined_on": joined_on,
            "activity_profile": activity_profile,
            "daily_budget": daily_budget,
        }
        filtered = {
            key: value
            for key, value in values.items()
            if key in supported_columns and value is not None
        }
        if existing is None:
            if "id" in supported_columns and id_type is not Integer:
                filtered.setdefault("id", str(uuid.uuid4()))
            result = connection.execute(user_mgmt.insert().values(**filtered))
            connection.commit()
            inserted_id = result.inserted_primary_key[0] if result.inserted_primary_key else None
            if inserted_id is None:
                inserted = connection.execute(
                    select(user_mgmt.c.id)
                    .where(user_mgmt.c.username == str(username))
                    .limit(1)
                ).first()
                if inserted is None:
                    raise RuntimeError(f"Failed to create plugin user '{username}'")
                return _raw_id(inserted[0])
            return _raw_id(inserted_id)
        connection.execute(
            user_mgmt.update().where(user_mgmt.c.id == existing[0]).values(**filtered)
        )
        connection.commit()
        return _raw_id(existing[0])

    def ensure_stress_reward_schema(self, connection: Connection) -> None:
        metadata = MetaData()
        id_type = self._id_sql_type(connection)
        stress_reward = Table(
            "stress_reward",
            metadata,
            Column("id", String(36), primary_key=True),
            Column("uid", id_type, nullable=False),
            Column("variable", String(32), nullable=False),
            Column("value", REAL, nullable=False),
            Column("type", String(32), nullable=False),
            Column("action", String(64), nullable=True),
            Column("tid", id_type, nullable=False),
            CheckConstraint("variable IN ('stress', 'reward')", name="ck_stress_reward_variable"),
            CheckConstraint("type IN ('aggregate', 'variation')", name="ck_stress_reward_type"),
            CheckConstraint(
                "(type = 'aggregate' AND value >= 0.0 AND value <= 1.0) OR "
                "(type = 'variation' AND value >= -1.0 AND value <= 1.0)",
                name="ck_stress_reward_value",
            ),
        )
        if not self.has_table(connection, "stress_reward"):
            stress_reward.create(connection, checkfirst=True)
            connection.commit()
            self._reflected_tables.pop("stress_reward", None)
            return
        columns = self._table_columns(connection, "stress_reward")
        if "action" not in columns:
            connection.execute(text("ALTER TABLE stress_reward ADD COLUMN action TEXT"))
            connection.commit()
            self._reflected_tables.pop("stress_reward", None)

    def get_user_type(self, connection: Connection, user_id: Any) -> str | None:
        user_mgmt = self.table("user_mgmt")
        row = connection.execute(
            select(user_mgmt.c.user_type).where(user_mgmt.c.id == user_id).limit(1)
        ).first()
        return None if row is None or row[0] is None else str(row[0])

    def get_current_stress_reward(
        self,
        connection: Connection,
        *,
        user_id: Any,
        current_round_id: Any,
        backward_rounds: int = 24,
    ) -> dict[str, float]:
        if not self.has_table(connection, "stress_reward"):
            return {"stress": 0.0, "reward": 0.0}
        stress_reward = self.table("stress_reward")
        rounds = self.table("rounds")
        current_round = connection.execute(
            select(rounds.c.id, rounds.c.day, rounds.c.hour)
            .where(rounds.c.id == current_round_id)
            .limit(1)
        ).mappings().first()
        if current_round is None:
            return {"stress": 0.0, "reward": 0.0}
        round_window = connection.execute(
            select(rounds.c.id)
            .where(
                (rounds.c.day < int(current_round["day"]))
                | (
                    (rounds.c.day == int(current_round["day"]))
                    & (rounds.c.hour <= int(current_round["hour"]))
                )
            )
            .order_by(rounds.c.day.desc(), rounds.c.hour.desc(), rounds.c.id.desc())
            .limit(max(1, int(backward_rounds) + 1))
        ).all()
        window_round_ids = [row[0] for row in round_window]
        payload: dict[str, float] = {"stress": 0.0, "reward": 0.0}
        for variable in ("stress", "reward"):
            exact = connection.execute(
                select(stress_reward.c.value)
                .where(stress_reward.c.uid == user_id)
                .where(stress_reward.c.variable == variable)
                .where(stress_reward.c.type == "aggregate")
                .where(stress_reward.c.tid == current_round_id)
                .limit(1)
            ).first()
            if exact is not None:
                payload[variable] = _clamp01(exact[0])
                continue

            anchor_value = 0.0
            anchor_row = connection.execute(
                select(stress_reward.c.tid, stress_reward.c.value, rounds.c.day, rounds.c.hour)
                .select_from(stress_reward.join(rounds, rounds.c.id == stress_reward.c.tid))
                .where(stress_reward.c.uid == user_id)
                .where(stress_reward.c.variable == variable)
                .where(stress_reward.c.type == "aggregate")
                .where(
                    (rounds.c.day < int(current_round["day"]))
                    | (
                        (rounds.c.day == int(current_round["day"]))
                        & (rounds.c.hour < int(current_round["hour"]))
                    )
                )
                .order_by(rounds.c.day.desc(), rounds.c.hour.desc(), stress_reward.c.tid.desc())
                .limit(1)
            ).first()
            anchor_tid = None
            if anchor_row is not None:
                anchor_tid = anchor_row[0]
                anchor_value = float(anchor_row[1] or 0.0)
            variation_statement = (
                select(func.coalesce(func.sum(stress_reward.c.value), 0.0))
                .where(stress_reward.c.uid == user_id)
                .where(stress_reward.c.variable == variable)
                .where(stress_reward.c.type == "variation")
                .where(stress_reward.c.tid.in_(tuple(window_round_ids)))
            )
            if anchor_tid is not None:
                variation_statement = variation_statement.where(stress_reward.c.tid != anchor_tid)
            variation_sum = connection.execute(variation_statement).scalar()
            payload[variable] = _clamp01(anchor_value + float(variation_sum or 0.0))
        return payload

    def set_stress_reward_variations(
        self,
        connection: Connection,
        *,
        user_id: Any,
        round_id: Any,
        variations: list[dict[str, Any]],
        action_name: str | None = None,
        aggregate_state: dict[str, float] | None = None,
    ) -> int:
        if not self.has_table(connection, "stress_reward"):
            return 0
        stress_reward = self.table("stress_reward")
        written = 0
        for variation in variations or []:
            variable = str((variation or {}).get("variable") or "").strip().lower()
            if variable not in {"stress", "reward"}:
                continue
            try:
                value = float((variation or {}).get("value"))
            except (TypeError, ValueError):
                continue
            if value < -1.0 or value > 1.0:
                continue
            connection.execute(
                stress_reward.insert().values(
                    id=str(uuid.uuid4()),
                    uid=user_id,
                    variable=variable,
                    value=value,
                    type="variation",
                    action=(str(action_name).strip() if action_name else None),
                    tid=round_id,
                )
            )
            written += 1

        if isinstance(aggregate_state, dict):
            for variable in ("stress", "reward"):
                if variable not in aggregate_state:
                    continue
                current_value = _clamp01(aggregate_state.get(variable))
                existing = connection.execute(
                    select(stress_reward.c.id)
                    .where(stress_reward.c.uid == user_id)
                    .where(stress_reward.c.variable == variable)
                    .where(stress_reward.c.type == "aggregate")
                    .where(stress_reward.c.tid == round_id)
                    .limit(1)
                ).first()
                if existing is None:
                    connection.execute(
                        stress_reward.insert().values(
                            id=str(uuid.uuid4()),
                            uid=user_id,
                            variable=variable,
                            value=current_value,
                            type="aggregate",
                            action=None,
                            tid=round_id,
                        )
                    )
                else:
                    connection.execute(
                        stress_reward.update()
                        .where(stress_reward.c.id == existing[0])
                        .values(value=current_value)
                    )

        if written or isinstance(aggregate_state, dict):
            connection.commit()
        return written

    def _insert_mentions_for_text(
        self,
        connection: Connection,
        *,
        text: str,
        post_id: Any,
        round_id: Any,
    ) -> None:
        if not text or not self.has_table(connection, "mentions"):
            return

        mention_table = self.table("mentions")
        usernames = {
            match.group(1).strip()
            for match in re.finditer(r"(?<!\w)@([A-Za-z0-9_]+)", str(text))
            if match.group(1).strip()
        }
        if not usernames:
            return

        user_mgmt = self.table("user_mgmt")
        rows = connection.execute(
            select(user_mgmt.c.id, user_mgmt.c.username).where(
                user_mgmt.c.username.in_(tuple(usernames))
            )
        ).mappings().all()
        if not rows:
            return

        existing_user_ids = {
            str(_raw_id(row[0]))
            for row in connection.execute(
                select(mention_table.c.user_id).where(mention_table.c.post_id == post_id)
            ).all()
        }
        for row in rows:
            user_id = _raw_id(row["id"])
            if str(user_id) in existing_user_ids:
                continue
            connection.execute(
                mention_table.insert().values(
                    user_id=user_id,
                    post_id=post_id,
                    round=round_id,
                    answered=0,
                )
            )

    def _insert_post_topics(
        self,
        connection: Connection,
        *,
        post_id: Any,
        topic_ids: list[int] | tuple[int, ...] | None,
    ) -> None:
        if not topic_ids or not self.has_table(connection, "post_topics"):
            return
        post_topics = self.table("post_topics")
        existing_topic_ids = {
            int(row[0])
            for row in connection.execute(
                select(post_topics.c.topic_id).where(post_topics.c.post_id == post_id)
            ).all()
        }
        for topic_id in topic_ids:
            topic_id = int(topic_id)
            if topic_id in existing_topic_ids:
                continue
            connection.execute(
                post_topics.insert().values(
                    post_id=post_id,
                    topic_id=topic_id,
                )
            )

    def get_latest_agent_opinion(
        self,
        connection: Connection,
        *,
        user_id: Any,
        topic_id: int,
        current_round_id: Any | None = None,
    ) -> float | None:
        if not self.has_table(connection, "agent_opinion"):
            return None
        agent_opinion = self.table("agent_opinion")
        rounds = self.table("rounds")
        statement = (
            select(agent_opinion.c.opinion, rounds.c.day, rounds.c.hour, agent_opinion.c.id)
            .select_from(agent_opinion.join(rounds, rounds.c.id == agent_opinion.c.tid))
            .where(agent_opinion.c.agent_id == user_id)
            .where(agent_opinion.c.topic_id == int(topic_id))
        )
        if current_round_id is not None:
            current_round = connection.execute(
                select(rounds.c.day, rounds.c.hour)
                .where(rounds.c.id == current_round_id)
                .limit(1)
            ).mappings().first()
            if current_round is None:
                return None
            statement = statement.where(
                (rounds.c.day < int(current_round["day"]))
                | (
                    (rounds.c.day == int(current_round["day"]))
                    & (rounds.c.hour <= int(current_round["hour"]))
                )
            )
        row = connection.execute(
            statement.order_by(rounds.c.day.desc(), rounds.c.hour.desc(), agent_opinion.c.id.desc()).limit(1)
        ).first()
        return None if row is None else float(row[0])

    def set_fixed_agent_opinion(
        self,
        connection: Connection,
        *,
        user_id: Any,
        topic_id: int,
        opinion: float,
        round_id: Any,
    ) -> bool:
        if not self.has_table(connection, "agent_opinion"):
            return False
        current = self.get_latest_agent_opinion(
            connection,
            user_id=user_id,
            topic_id=int(topic_id),
            current_round_id=None,
        )
        if current is not None and abs(float(current) - float(opinion)) <= 1e-9:
            return False
        agent_opinion = self.table("agent_opinion")
        connection.execute(
            agent_opinion.insert().values(
                agent_id=user_id,
                tid=round_id,
                topic_id=int(topic_id),
                id_interacted_with=-1,
                id_post=-1,
                opinion=float(opinion),
            )
        )
        connection.commit()
        return True

    def get_latest_opinions_for_topic(
        self,
        connection: Connection,
        *,
        topic_id: int,
        current_round_id: Any | None = None,
    ) -> tuple[dict[str, Any], ...]:
        if not self.has_table(connection, "agent_opinion"):
            return ()
        agent_opinion = self.table("agent_opinion")
        rounds = self.table("rounds")
        statement = select(
            agent_opinion.c.agent_id,
            agent_opinion.c.opinion,
            agent_opinion.c.tid,
            agent_opinion.c.id,
            rounds.c.day,
            rounds.c.hour,
        ).select_from(agent_opinion.join(rounds, rounds.c.id == agent_opinion.c.tid)).where(agent_opinion.c.topic_id == int(topic_id))
        if current_round_id is not None:
            current_round = connection.execute(
                select(rounds.c.day, rounds.c.hour)
                .where(rounds.c.id == current_round_id)
                .limit(1)
            ).mappings().first()
            if current_round is None:
                return ()
            statement = statement.where(
                (rounds.c.day < int(current_round["day"]))
                | (
                    (rounds.c.day == int(current_round["day"]))
                    & (rounds.c.hour <= int(current_round["hour"]))
                )
            )
        rows = connection.execute(
            statement.order_by(
                agent_opinion.c.agent_id.asc(),
                rounds.c.day.desc(),
                rounds.c.hour.desc(),
                agent_opinion.c.id.desc(),
            )
        ).mappings().all()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            agent_id = _raw_id(row["agent_id"])
            agent_key = str(agent_id)
            if agent_key in latest:
                continue
            latest[agent_key] = {
                "user_id": agent_id,
                "opinion": float(row["opinion"]),
                "round_id": _raw_id(row["tid"]),
            }
        return tuple(latest.values())

    def resolve_interest_topic_id(
        self,
        connection: Connection,
        *,
        configured_topic_id: int | None = None,
        topic_name: str | None = None,
    ) -> int | None:
        if not self.has_table(connection, "interests"):
            return configured_topic_id
        interests = self.table("interests")
        interest_column = (
            interests.c.interest
            if "interest" in interests.c
            else interests.c.topic
            if "topic" in interests.c
            else None
        )
        if configured_topic_id is not None:
            row = connection.execute(
                select(interests.c.iid)
                .where(interests.c.iid == int(configured_topic_id))
                .limit(1)
            ).first()
            if row is not None:
                return int(row[0])
        normalized_name = str(topic_name or "").strip()
        if interest_column is None or not normalized_name:
            return None
        rows = connection.execute(select(interests.c.iid, interest_column)).all()
        for row in rows:
            if str(row[1] or "").strip().casefold() == normalized_name.casefold():
                return int(row[0])
        return None

    def get_thread_posts(
        self,
        connection: Connection,
        *,
        thread_id: Any,
        limit: int = 20,
    ) -> tuple[PostRecord, ...]:
        post = self.table("post")
        rounds = self.table("rounds")
        statement = (
            select(
                post.c.id,
                post.c.user_id,
                post.c.tweet,
                post.c.round,
                rounds.c.day.label("round_day"),
                rounds.c.hour.label("round_hour"),
                post.c.comment_to,
                post.c.thread_id,
                post.c.shared_from,
                (post.c.moderated if "moderated" in post.c else literal(0)).label("moderated"),
                (
                    post.c.is_moderation_comment
                    if "is_moderation_comment" in post.c
                    else literal(0)
                ).label("is_moderation_comment"),
                literal(None).label("toxicity"),
                literal(0).label("reported_count"),
            )
            .select_from(post.join(rounds, rounds.c.id == post.c.round))
            .where((post.c.id == thread_id) | (post.c.thread_id == thread_id))
            .order_by(rounds.c.day.asc(), rounds.c.hour.asc(), post.c.id.asc())
            .limit(int(limit))
        )
        rows = connection.execute(statement).mappings().all()
        return tuple(
            PostRecord(
                id=_raw_id(row["id"]),
                author_id=_raw_id(row["user_id"]),
                text=str(row["tweet"]),
                round_id=_raw_id(row["round"]),
                comment_to=_nullable_id(row["comment_to"]),
                thread_id=_nullable_id(row["thread_id"]),
                shared_from=_nullable_id(row["shared_from"]),
                round_day=int(row["round_day"]) if row["round_day"] is not None else None,
                round_slot=int(row["round_hour"]) if row["round_hour"] is not None else None,
                moderated=int(row["moderated"] or 0),
                is_moderation_comment=int(row["is_moderation_comment"] or 0),
                toxicity=None,
                reported_count=int(row["reported_count"] or 0),
            )
            for row in rows
        )

    def get_latest_thread_post_by_user(
        self,
        connection: Connection,
        *,
        thread_id: Any,
        user_id: Any,
        after_round_id: Any | None = None,
    ) -> PostRecord | None:
        posts = self.get_thread_posts(connection, thread_id=thread_id, limit=200)
        candidates = [
            post
            for post in posts
            if str(post.author_id) == str(user_id)
            and (
                after_round_id is None
                or post.round_ordinal > self._round_ordinal_for_id(connection, after_round_id)
            )
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda post: (post.round_ordinal, str(post.id)))

    def get_latest_thread_post_excluding_users(
        self,
        connection: Connection,
        *,
        thread_id: Any,
        excluded_user_ids: set[Any] | list[Any] | tuple[Any, ...],
        after_round_id: Any | None = None,
    ) -> PostRecord | None:
        excluded = {str(user_id) for user_id in excluded_user_ids}
        posts = self.get_thread_posts(connection, thread_id=thread_id, limit=200)
        candidates = [
            post
            for post in posts
            if str(post.author_id) not in excluded
            and (
                after_round_id is None
                or post.round_ordinal > self._round_ordinal_for_id(connection, after_round_id)
            )
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda post: (post.round_ordinal, str(post.id)))

    def get_posts_by_author_ids_since_round(
        self,
        connection: Connection,
        *,
        author_ids: list[Any] | tuple[Any, ...] | set[Any],
        min_round_id: int,
        limit: int = 100,
    ) -> tuple[PostRecord, ...]:
        author_ids = list(author_ids)
        if not author_ids:
            return ()
        post = self.table("post")
        rounds = self.table("rounds")
        rows = connection.execute(
            select(
                post.c.id,
                post.c.user_id,
                post.c.tweet,
                post.c.round,
                rounds.c.day.label("round_day"),
                rounds.c.hour.label("round_hour"),
                post.c.comment_to,
                post.c.thread_id,
                post.c.shared_from,
                (post.c.moderated if "moderated" in post.c else literal(0)).label("moderated"),
                (
                    post.c.is_moderation_comment
                    if "is_moderation_comment" in post.c
                    else literal(0)
                ).label("is_moderation_comment"),
                literal(None).label("toxicity"),
                literal(0).label("reported_count"),
            )
            .select_from(post.join(rounds, rounds.c.id == post.c.round))
            .where(post.c.user_id.in_(author_ids))
            .where((rounds.c.day * 24 + rounds.c.hour) >= int(min_round_id))
            .order_by(rounds.c.day.desc(), rounds.c.hour.desc(), post.c.id.desc())
            .limit(int(limit))
        ).mappings().all()
        return tuple(
            PostRecord(
                id=_raw_id(row["id"]),
                author_id=_raw_id(row["user_id"]),
                text=str(row["tweet"]),
                round_id=_raw_id(row["round"]),
                comment_to=_nullable_id(row["comment_to"]),
                thread_id=_nullable_id(row["thread_id"]),
                shared_from=_nullable_id(row["shared_from"]),
                round_day=int(row["round_day"]) if row["round_day"] is not None else None,
                round_slot=int(row["round_hour"]) if row["round_hour"] is not None else None,
                moderated=int(row["moderated"] or 0),
                is_moderation_comment=int(row["is_moderation_comment"] or 0),
                toxicity=None,
                reported_count=int(row["reported_count"] or 0),
            )
            for row in rows
        )

    def get_followed_user_ids(
        self,
        connection: Connection,
        *,
        username: str,
    ) -> set[Any]:
        if not self.has_table(connection, "follow"):
            return set()
        follow = self.table("follow")
        user_id = self.get_user_id(connection, username)
        rows = connection.execute(
            select(follow.c.follower_id, follow.c.action)
            .where(follow.c.user_id == user_id)
            .order_by(follow.c.round.asc(), follow.c.id.asc())
        ).all()
        followed: set[Any] = set()
        for target_id, action in rows:
            if str(action or "").strip().lower() == "follow":
                followed.add(_raw_id(target_id))
            elif str(action or "").strip().lower() == "unfollow":
                followed.discard(_raw_id(target_id))
        return followed

    def insert_propaganda_activity(
        self,
        connection: Connection,
        *,
        target_uid: Any,
        propaganda_agent_uid: Any,
        thread_id: Any,
        discussion_round_id: Any,
        target_opinion: float | None,
        topic_id: int,
    ) -> int:
        activity = self.table("propaganda_activity")
        result = connection.execute(
            activity.insert()
            .values(
                target_uid=target_uid,
                propaganda_agent_uid=propaganda_agent_uid,
                thread_id=thread_id,
                discussion_round_id=discussion_round_id,
                target_opinion=target_opinion,
                topic_id=int(topic_id),
            )
            .returning(activity.c.id)
        )
        activity_id = int(result.scalar_one())
        connection.commit()
        return activity_id

    def count_propaganda_actions_for_thread(
        self,
        connection: Connection,
        *,
        propaganda_agent_uid: Any,
        thread_id: Any,
    ) -> int:
        if not self.has_table(connection, "propaganda_activity"):
            return 0
        activity = self.table("propaganda_activity")
        row = connection.execute(
            select(func.count())
            .select_from(activity)
            .where(activity.c.propaganda_agent_uid == propaganda_agent_uid)
            .where(activity.c.thread_id == thread_id)
        ).first()
        return int(row[0] or 0)

    def get_latest_propaganda_thread_state(
        self,
        connection: Connection,
        *,
        propaganda_agent_uid: Any,
    ) -> dict[str, Any] | None:
        if not self.has_table(connection, "propaganda_activity"):
            return None
        activity = self.table("propaganda_activity")
        row = connection.execute(
            select(activity)
            .where(activity.c.propaganda_agent_uid == propaganda_agent_uid)
            .order_by(activity.c.id.desc())
            .limit(1)
        ).mappings().first()
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "target_uid": _raw_id(row["target_uid"]),
            "propaganda_agent_uid": _raw_id(row["propaganda_agent_uid"]),
            "thread_id": _raw_id(row["thread_id"]),
            "discussion_round_id": _raw_id(row["discussion_round_id"]),
            "target_opinion": (
                None if row["target_opinion"] is None else float(row["target_opinion"])
            ),
            "topic_id": int(row["topic_id"]),
        }

    def get_latest_propaganda_thread_states(
        self,
        connection: Connection,
        *,
        propaganda_agent_uid: Any,
    ) -> tuple[dict[str, Any], ...]:
        if not self.has_table(connection, "propaganda_activity"):
            return ()
        activity = self.table("propaganda_activity")
        rows = connection.execute(
            select(activity)
            .where(activity.c.propaganda_agent_uid == propaganda_agent_uid)
            .order_by(activity.c.thread_id.asc(), activity.c.id.desc())
        ).mappings().all()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            thread_id = _raw_id(row["thread_id"])
            thread_key = str(thread_id)
            if thread_key in latest:
                continue
            latest[thread_key] = {
                "id": int(row["id"]),
                "target_uid": _raw_id(row["target_uid"]),
                "propaganda_agent_uid": _raw_id(row["propaganda_agent_uid"]),
                "thread_id": thread_id,
                "discussion_round_id": _raw_id(row["discussion_round_id"]),
                "target_opinion": (
                    None if row["target_opinion"] is None else float(row["target_opinion"])
                ),
                "topic_id": int(row["topic_id"]),
            }
        return tuple(latest.values())

    def count_posts_by_username_and_text(
        self,
        connection: Connection,
        *,
        username: str,
        text: str,
    ) -> int:
        post = self.table("post")
        user_mgmt = self.table("user_mgmt")
        row = connection.execute(
            select(func.count())
            .select_from(post.join(user_mgmt, user_mgmt.c.id == post.c.user_id))
            .where(user_mgmt.c.username == username)
            .where(post.c.tweet == text)
        ).first()
        return int(row[0])

    def _table_columns(self, connection: Connection, table_name: str) -> set[str]:
        return {column["name"] for column in inspect(connection).get_columns(table_name)}

    def table(self, table_name: str) -> Table:
        if table_name not in self._reflected_tables:
            self._reflected_tables[table_name] = Table(
                table_name,
                self.metadata,
                autoload_with=self.engine,
                extend_existing=True,
            )
        return self._reflected_tables[table_name]

    def create_tables(self, *tables: Table) -> None:
        if not tables:
            return
        self.metadata.create_all(self.engine, tables=list(tables), checkfirst=True)

    def has_table(self, connection: Connection, table_name: str) -> bool:
        return inspect(connection).has_table(table_name)

    def insert_moderation_event(
        self,
        connection: Connection,
        *,
        moderator_username: str,
        moderated_post_id: Any,
        moderation_type: str,
        round_id: Any,
        generated_comment_id: Any | None = None,
    ) -> int:
        actions = self.table("plugin_moderation_actions")
        moderated_agent_id = self.get_post_author_id(connection, moderated_post_id)
        moderator_id = self.get_user_id(connection, moderator_username)
        result = connection.execute(
            actions.insert()
            .values(
                moderated_post_id=moderated_post_id,
                moderated_agent_id=moderated_agent_id,
                moderator_agent_id=moderator_id,
                moderation_type=moderation_type,
                round_id=round_id,
                generated_comment_id=generated_comment_id,
            )
            .returning(actions.c.id)
        )
        action_id = int(result.scalar_one())
        self.increment_moderation_count(
            connection,
            moderated_agent_id=moderated_agent_id,
        )
        connection.commit()
        return action_id

    def create_system_message(
        self,
        connection: Connection,
        *,
        message_type: str,
        to_user_id: Any,
        message: str,
        from_round: Any,
        duration: int,
    ) -> int:
        sys_messages = self.table("sys_messages")
        values = {
            "type": message_type,
            "to_uid": to_user_id,
            "message": message,
            "from_round": from_round,
        }
        if "duration" in sys_messages.c:
            values["duration"] = duration
        elif "to_round" in sys_messages.c:
            values["to_round"] = self._round_id_after_offset(
                connection,
                start_round_id=from_round,
                offset=duration,
            )
        else:
            raise RuntimeError("sys_messages table exposes neither duration nor to_round")
        result = connection.execute(
            sys_messages.insert()
            .values(**values)
            .returning(sys_messages.c.id)
        )
        message_id = int(result.scalar_one())
        connection.commit()
        return message_id

    def mark_post_moderated(self, connection: Connection, *, post_id: Any) -> None:
        post = self.table("post")
        if "moderated" not in post.c:
            raise RuntimeError("post table does not expose a moderated column")
        connection.execute(
            post.update().where(post.c.id == post_id).values(moderated=1)
        )
        connection.commit()

    def increment_moderation_count(
        self,
        connection: Connection,
        *,
        moderated_agent_id: Any,
    ) -> None:
        counts = self.table("plugin_moderation_counts")
        existing = connection.execute(
            select(counts.c.moderated_agent_id, counts.c.moderation_count)
            .where(counts.c.moderated_agent_id == moderated_agent_id)
            .limit(1)
        ).first()
        if existing is None:
            connection.execute(
                counts.insert().values(
                    moderated_agent_id=moderated_agent_id,
                    moderation_count=1,
                )
            )
        else:
            connection.execute(
                counts.update()
                .where(counts.c.moderated_agent_id == moderated_agent_id)
                .values(moderation_count=int(existing[1]) + 1)
            )

    def count_moderations_for_agent_day(
        self,
        connection: Connection,
        *,
        moderator_username: str,
        day: int,
    ) -> int:
        actions = self.table("plugin_moderation_actions")
        rounds = self.table("rounds")
        moderator_id = self.get_user_id(connection, moderator_username)
        row = connection.execute(
            select(func.count())
            .select_from(actions.join(rounds, rounds.c.id == actions.c.round_id))
            .where(actions.c.moderator_agent_id == moderator_id)
            .where(rounds.c.day == day)
        ).first()
        return int(row[0] or 0)

    def count_recent_infractions_for_user(
        self,
        connection: Connection,
        *,
        user_id: Any,
        current_round_id: Any,
        window_rounds: int,
    ) -> int:
        actions = self.table("plugin_moderation_actions")
        current_round_ordinal = self._round_ordinal_for_id(connection, current_round_id)
        lower_bound = max(0, current_round_ordinal - max(0, int(window_rounds)))
        rounds = self.table("rounds")
        row = connection.execute(
            select(func.count())
            .select_from(actions.join(rounds, rounds.c.id == actions.c.round_id))
            .where(actions.c.moderated_agent_id == user_id)
            .where((rounds.c.day * 24 + rounds.c.hour) >= lower_bound)
            .where((rounds.c.day * 24 + rounds.c.hour) <= current_round_ordinal)
        ).first()
        return int(row[0] or 0)

    def create_shadow_ban(
        self,
        connection: Connection,
        *,
        user_id: Any,
        start_tid: Any,
        duration: int,
    ) -> None:
        if not self.has_table(connection, "shadow_ban"):
            return
        shadow_ban = self.table("shadow_ban")
        existing = connection.execute(
            select(shadow_ban.c.uid)
            .where(shadow_ban.c.uid == user_id)
            .where(shadow_ban.c.start_tid == start_tid)
            .limit(1)
        ).first()
        if existing is None:
            connection.execute(
                shadow_ban.insert().values(
                    uid=user_id,
                    start_tid=start_tid,
                    duration=int(duration),
                )
            )
            connection.commit()

    def create_ban(
        self,
        connection: Connection,
        *,
        user_id: Any,
        round_id: Any,
    ) -> None:
        user_mgmt = self.table("user_mgmt")
        if "left_on" in user_mgmt.c:
            connection.execute(
                user_mgmt.update().where(user_mgmt.c.id == user_id).values(left_on=round_id)
            )
        if self.has_table(connection, "banned"):
            banned = self.table("banned")
            existing = connection.execute(
                select(banned.c.uid).where(banned.c.uid == user_id).limit(1)
            ).first()
            if existing is None:
                connection.execute(
                    banned.insert().values(
                        uid=user_id,
                        tid=round_id,
                    )
                )
        connection.commit()

    def user_is_banned(
        self,
        connection: Connection,
        *,
        user_id: Any,
    ) -> bool:
        user_mgmt = self.table("user_mgmt")
        if "left_on" in user_mgmt.c:
            row = connection.execute(
                select(user_mgmt.c.left_on).where(user_mgmt.c.id == user_id).limit(1)
            ).first()
            return row is not None and row[0] is not None
        if self.has_table(connection, "banned"):
            banned = self.table("banned")
            row = connection.execute(
                select(banned.c.uid).where(banned.c.uid == user_id).limit(1)
            ).first()
            return row is not None
        return False

    def user_has_active_shadow_ban(
        self,
        connection: Connection,
        *,
        user_id: Any,
        current_round_id: Any,
    ) -> bool:
        if not self.has_table(connection, "shadow_ban"):
            return False
        shadow_ban = self.table("shadow_ban")
        rows = connection.execute(
            select(shadow_ban.c.uid, shadow_ban.c.start_tid, shadow_ban.c.duration)
            .where(shadow_ban.c.uid == user_id)
        ).all()
        current_ordinal = self._round_ordinal_for_id(connection, current_round_id)
        for _uid, start_tid, duration in rows:
            start_ordinal = self._round_ordinal_for_id(connection, start_tid)
            if start_ordinal > current_ordinal:
                continue
            if duration in (None, ""):
                return True
            if start_ordinal + int(duration) >= current_ordinal:
                return True
        return False

    def seed_table_rows(
        self,
        connection: Connection,
        table_name: str,
        *,
        rows: list[dict[str, Any]],
        key_column: str,
    ) -> None:
        if not rows:
            return
        table = self.table(table_name)
        for row in rows:
            existing = connection.execute(
                select(getattr(table.c, key_column))
                .where(getattr(table.c, key_column) == row[key_column])
                .limit(1)
            ).first()
            if existing is None:
                connection.execute(table.insert().values(**row))
        connection.commit()

    def get_post_author_id(self, connection: Connection, post_id: Any) -> Any:
        post = self.table("post")
        row = connection.execute(
            select(post.c.user_id).where(post.c.id == post_id).limit(1)
        ).first()
        if row is None:
            raise RuntimeError(f"Post '{post_id}' not found in post table")
        return _raw_id(row[0])

    def get_thread_post_count_for_post(
        self,
        connection: Connection,
        *,
        post_id: Any,
    ) -> int:
        post = self.table("post")
        row = connection.execute(
            select(post.c.id, post.c.thread_id).where(post.c.id == post_id).limit(1)
        ).mappings().first()
        if row is None:
            raise RuntimeError(f"Post '{post_id}' not found in post table")
        thread_id = _nullable_id(row["thread_id"]) or _raw_id(row["id"])
        return len(self.get_thread_posts(connection, thread_id=thread_id, limit=500))

    def count_rows(self, connection: Connection, table_name: str) -> int:
        table = self.table(table_name)
        row = connection.execute(select(func.count()).select_from(table)).first()
        return int(row[0])

    def count_rows_for_user_day(
        self,
        connection: Connection,
        *,
        table_name: str,
        user_column: str,
        user_id: Any,
        day: int,
    ) -> int:
        if not self.has_table(connection, table_name):
            return 0
        table = self.table(table_name)
        if table_name == "activity_logs" and "round_id" in table.c:
            lower_bound = int(day) * 24
            upper_bound = lower_bound + 23
            row = connection.execute(
                select(func.count())
                .select_from(table)
                .where(getattr(table.c, user_column) == user_id)
                .where(table.c.round_id >= lower_bound)
                .where(table.c.round_id <= upper_bound)
            ).first()
            return int(row[0] or 0)
        rounds = self.table("rounds")
        round_column = (
            table.c.round_id
            if "round_id" in table.c
            else table.c.discussion_round_id
        )
        row = connection.execute(
            select(func.count())
            .select_from(table.join(rounds, rounds.c.id == round_column))
            .where(getattr(table.c, user_column) == user_id)
            .where(rounds.c.day == int(day))
        ).first()
        return int(row[0] or 0)

    def _round_id_after_offset(
        self,
        connection: Connection,
        *,
        start_round_id: Any,
        offset: int,
    ) -> Any:
        rounds = self.table("rounds")
        ordered = connection.execute(
            select(rounds.c.id)
            .order_by(rounds.c.day.asc(), rounds.c.hour.asc(), rounds.c.id.asc())
        ).all()
        if not ordered:
            return start_round_id
        round_ids = [_raw_id(row[0]) for row in ordered]
        try:
            start_index = next(
                idx for idx, candidate in enumerate(round_ids) if str(candidate) == str(start_round_id)
            )
        except StopIteration:
            return start_round_id
        target_index = max(0, min(len(round_ids) - 1, start_index + int(offset)))
        return round_ids[target_index]

    def _validate_connectivity(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def _id_sql_type(self, connection: Connection):
        rounds = self.table("rounds")
        row = connection.execute(select(rounds.c.id).limit(1)).first()
        if row is None or row[0] is None:
            return Integer
        value = row[0]
        if isinstance(value, int):
            return Integer
        text_value = str(value).strip()
        return Integer if text_value.isdigit() else String(64)

    def _max_score_expr(self, *columns):
        if not columns:
            return literal(0.0)
        normalized = [func.coalesce(column, 0.0) for column in columns]
        if len(normalized) == 1:
            return normalized[0]
        if self.engine.dialect.name == "sqlite":
            return func.max(*normalized)
        return func.greatest(*normalized)

    @staticmethod
    def _normalize_database_url(database_url: str | Path) -> str:
        if isinstance(database_url, Path):
            resolved = database_url.expanduser().resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"Experiment database not found: {resolved}")
            return f"sqlite:///{resolved}"

        raw = str(database_url)
        if "://" in raw:
            if raw.startswith("sqlite:///"):
                sqlite_file = Path(raw.removeprefix("sqlite:///")).expanduser().resolve()
                if not sqlite_file.exists():
                    raise FileNotFoundError(f"Experiment database not found: {sqlite_file}")
            return raw

        resolved = Path(raw).expanduser().resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Experiment database not found: {resolved}")
        return f"sqlite:///{resolved}"

    def _round_ordinal_for_id(self, connection: Connection, round_id: Any) -> int:
        rounds = self.table("rounds")
        row = connection.execute(
            select(rounds.c.day, rounds.c.hour).where(rounds.c.id == round_id).limit(1)
        ).first()
        if row is None:
            return 0
        return int(row[0]) * 24 + int(row[1])

    @staticmethod
    def _round_from_row(row: RowMapping) -> SimulationRound:
        return SimulationRound(id=_raw_id(row["id"]), day=int(row["day"]), slot=int(row["hour"]))


def _raw_id(value: object) -> Any:
    if value is None:
        return None
    return value


def _nullable_id(value: object) -> Any | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return None if text_value == "-1" else value


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0
