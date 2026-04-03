from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, func, inspect, select, text
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
        rows = connection.execute(
            select(
                post.c.id,
                post.c.user_id,
                post.c.tweet,
                post.c.round,
                post.c.comment_to,
                post.c.thread_id,
                post.c.shared_from,
            )
            .where(post.c.round <= round_id)
            .order_by(post.c.id.desc())
            .limit(limit)
        ).mappings().all()
        return tuple(
            PostRecord(
                id=int(row["id"]),
                author_id=int(row["user_id"]),
                text=str(row["tweet"]),
                round_id=int(row["round"]),
                comment_to=_nullable_int(row["comment_to"]),
                thread_id=_nullable_int(row["thread_id"]),
                shared_from=_nullable_int(row["shared_from"]),
            )
            for row in rows
        )

    def get_users(self, connection: Connection) -> tuple[UserRecord, ...]:
        user_mgmt = self.table("user_mgmt")
        rows = connection.execute(
            select(
                user_mgmt.c.id,
                user_mgmt.c.username,
                user_mgmt.c.user_type,
                user_mgmt.c.owner,
            ).order_by(user_mgmt.c.id.asc())
        ).mappings().all()
        return tuple(
            UserRecord(
                id=int(row["id"]),
                username=str(row["username"]),
                user_type=row["user_type"],
                owner=row["owner"],
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
    ) -> int:
        post = self.table("post")
        user_id = self.get_user_id(connection, username)
        parent = connection.execute(
            select(post.c.id, post.c.thread_id).where(post.c.id == parent_post_id).limit(1)
        ).mappings().first()
        if parent is None:
            raise RuntimeError(f"Parent post '{parent_post_id}' not found in post table")
        thread_id = _nullable_int(parent["thread_id"]) or int(parent["id"])
        result = connection.execute(
            post.insert()
            .values(
                tweet=text,
                user_id=user_id,
                comment_to=parent_post_id,
                thread_id=thread_id,
                round=round_id,
                shared_from=-1,
            )
            .returning(post.c.id)
        )
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
