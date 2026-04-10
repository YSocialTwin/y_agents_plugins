from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, func, inspect, literal, select, text
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.pool import NullPool

from y_agents_plugins.core.models import AgentSpec, PostRecord, SimulationRound, UserRecord


class ExperimentDatabase:
    """SQLAlchemy gateway for experiment and plugin-owned tables."""

    def __init__(self, database_url: str | Path):
        self.database_url = self._normalize_database_url(database_url)
        self.engine: Engine = create_engine(
            self.database_url,
            future=True,
            pool_pre_ping=True,
            poolclass=NullPool,
        )
        self.metadata = MetaData()
        self._reflected_tables: dict[str, Table] = {}
        self._validate_connectivity()

    def connect(self) -> Connection:
        return self.engine.connect()

    def get_current_round(self, connection: Connection) -> SimulationRound:
        rounds = self.table("rounds")
        row = connection.execute(
            select(rounds.c.id, rounds.c.day, rounds.c.hour).order_by(rounds.c.id.desc()).limit(1)
        ).mappings().first()
        if row is None:
            raise RuntimeError("No rows found in rounds table")
        return self._round_from_row(row)

    def get_rounds_after(
        self,
        connection: Connection,
        after_round_id: int | None,
    ) -> tuple[SimulationRound, ...]:
        rounds = self.table("rounds")
        statement = select(rounds.c.id, rounds.c.day, rounds.c.hour).order_by(rounds.c.id.asc())
        if after_round_id is None:
            rows = connection.execute(statement).mappings().all()
        else:
            rows = connection.execute(statement.where(rounds.c.id > after_round_id)).mappings().all()
        return tuple(self._round_from_row(row) for row in rows)

    def get_recent_posts(
        self,
        connection: Connection,
        *,
        round_id: int,
        limit: int,
    ) -> tuple[PostRecord, ...]:
        post = self.table("post")
        statement = select(
            post.c.id,
            post.c.user_id,
            post.c.tweet,
            post.c.round,
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
        ).where(post.c.round <= round_id)

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
                post.c.comment_to,
                post.c.thread_id,
                post.c.shared_from,
                (post.c.moderated if "moderated" in post.c else literal(0)).label("moderated"),
                statement.selected_columns.is_moderation_comment,
                statement.selected_columns.toxicity,
                func.coalesce(reported_subquery.c.reported_count, 0).label("reported_count"),
            )

        rows = connection.execute(statement.order_by(post.c.id.desc()).limit(limit)).mappings().all()
        return tuple(
            PostRecord(
                id=int(row["id"]),
                author_id=int(row["user_id"]),
                text=str(row["tweet"]),
                round_id=int(row["round"]),
                comment_to=_nullable_int(row["comment_to"]),
                thread_id=_nullable_int(row["thread_id"]),
                shared_from=_nullable_int(row["shared_from"]),
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
                id=int(row["id"]),
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

    def get_user_id(self, connection: Connection, username: str) -> int:
        user_mgmt = self.table("user_mgmt")
        row = connection.execute(
            select(user_mgmt.c.id).where(user_mgmt.c.username == username).limit(1)
        ).first()
        if row is None:
            raise RuntimeError(f"User '{username}' not found in user_mgmt")
        return int(row[0])

    def register_agents(
        self,
        connection: Connection,
        agents: tuple[AgentSpec, ...],
        *,
        joined_on: int,
    ) -> None:
        user_mgmt = self.table("user_mgmt")
        supported_columns = self._table_columns(connection, "user_mgmt")
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
                connection.execute(user_mgmt.insert().values(**filtered_values))
            else:
                connection.execute(
                    user_mgmt.update().where(user_mgmt.c.id == int(existing[0])).values(**filtered_values)
                )
        connection.commit()

    def create_post(
        self,
        connection: Connection,
        *,
        username: str,
        text: str,
        round_id: int,
    ) -> int:
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
        post_id = int(result.scalar_one())
        connection.commit()
        return post_id

    def create_comment(
        self,
        connection: Connection,
        *,
        username: str,
        text: str,
        round_id: int,
        parent_post_id: int,
        is_moderation_comment: bool = False,
    ) -> int:
        post = self.table("post")
        user_id = self.get_user_id(connection, username)
        parent = connection.execute(
            select(post.c.id, post.c.thread_id).where(post.c.id == parent_post_id).limit(1)
        ).mappings().first()
        if parent is None:
            raise RuntimeError(f"Parent post '{parent_post_id}' not found in post table")
        thread_id = _nullable_int(parent["thread_id"]) or int(parent["id"])
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
        comment_id = int(result.scalar_one())
        connection.commit()
        return comment_id

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
        moderated_post_id: int,
        moderation_type: str,
        round_id: int,
        generated_comment_id: int | None = None,
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
        to_user_id: int,
        message: str,
        from_round: int,
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
            values["to_round"] = from_round + duration
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

    def mark_post_moderated(self, connection: Connection, *, post_id: int) -> None:
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
        moderated_agent_id: int,
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
        user_id: int,
        current_round_id: int,
        window_rounds: int,
    ) -> int:
        actions = self.table("plugin_moderation_actions")
        lower_bound = max(0, int(current_round_id) - max(0, int(window_rounds)))
        row = connection.execute(
            select(func.count())
            .select_from(actions)
            .where(actions.c.moderated_agent_id == int(user_id))
            .where(actions.c.round_id >= lower_bound)
            .where(actions.c.round_id <= int(current_round_id))
        ).first()
        return int(row[0] or 0)

    def create_shadow_ban(
        self,
        connection: Connection,
        *,
        user_id: int,
        start_tid: int,
        duration: int,
    ) -> None:
        if not self.has_table(connection, "shadow_ban"):
            return
        shadow_ban = self.table("shadow_ban")
        existing = connection.execute(
            select(shadow_ban.c.uid)
            .where(shadow_ban.c.uid == int(user_id))
            .where(shadow_ban.c.start_tid == int(start_tid))
            .limit(1)
        ).first()
        if existing is None:
            connection.execute(
                shadow_ban.insert().values(
                    uid=int(user_id),
                    start_tid=int(start_tid),
                    duration=int(duration),
                )
            )
            connection.commit()

    def create_ban(
        self,
        connection: Connection,
        *,
        user_id: int,
        round_id: int,
    ) -> None:
        user_mgmt = self.table("user_mgmt")
        if "left_on" in user_mgmt.c:
            connection.execute(
                user_mgmt.update().where(user_mgmt.c.id == int(user_id)).values(left_on=int(round_id))
            )
        if self.has_table(connection, "banned"):
            banned = self.table("banned")
            existing = connection.execute(
                select(banned.c.uid).where(banned.c.uid == int(user_id)).limit(1)
            ).first()
            if existing is None:
                connection.execute(
                    banned.insert().values(
                        uid=int(user_id),
                        tid=int(round_id),
                    )
                )
        connection.commit()

    def user_is_banned(
        self,
        connection: Connection,
        *,
        user_id: int,
    ) -> bool:
        user_mgmt = self.table("user_mgmt")
        if "left_on" in user_mgmt.c:
            row = connection.execute(
                select(user_mgmt.c.left_on).where(user_mgmt.c.id == int(user_id)).limit(1)
            ).first()
            return row is not None and row[0] is not None
        if self.has_table(connection, "banned"):
            banned = self.table("banned")
            row = connection.execute(
                select(banned.c.uid).where(banned.c.uid == int(user_id)).limit(1)
            ).first()
            return row is not None
        return False

    def user_has_active_shadow_ban(
        self,
        connection: Connection,
        *,
        user_id: int,
        current_round_id: int,
    ) -> bool:
        if not self.has_table(connection, "shadow_ban"):
            return False
        shadow_ban = self.table("shadow_ban")
        row = connection.execute(
            select(shadow_ban.c.uid)
            .where(shadow_ban.c.uid == int(user_id))
            .where(shadow_ban.c.start_tid <= int(current_round_id))
            .where((shadow_ban.c.duration.is_(None)) | ((shadow_ban.c.start_tid + shadow_ban.c.duration) >= int(current_round_id)))
            .limit(1)
        ).first()
        return row is not None

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

    def get_post_author_id(self, connection: Connection, post_id: int) -> int:
        post = self.table("post")
        row = connection.execute(
            select(post.c.user_id).where(post.c.id == post_id).limit(1)
        ).first()
        if row is None:
            raise RuntimeError(f"Post '{post_id}' not found in post table")
        return int(row[0])

    def count_rows(self, connection: Connection, table_name: str) -> int:
        table = self.table(table_name)
        row = connection.execute(select(func.count()).select_from(table)).first()
        return int(row[0])

    def _validate_connectivity(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

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

    @staticmethod
    def _round_from_row(row: RowMapping) -> SimulationRound:
        return SimulationRound(id=int(row["id"]), day=int(row["day"]), slot=int(row["hour"]))


def _nullable_int(value: object) -> int | None:
    if value is None:
        return None
    numeric = int(value)
    return None if numeric < 0 else numeric
