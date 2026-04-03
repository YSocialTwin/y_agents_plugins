from __future__ import annotations

import sqlite3
from pathlib import Path

from y_agents_plugins.models import AgentSpec, PostRecord, SimulationRound, UserRecord


class ExperimentDatabase:
    """Direct SQLite access to the YSocial experiment database."""

    def __init__(self, sqlite_path: str | Path):
        self.sqlite_path = Path(sqlite_path).expanduser().resolve()
        if not self.sqlite_path.exists():
            raise FileNotFoundError(f"Experiment database not found: {self.sqlite_path}")

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.sqlite_path,
            timeout=30,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        return connection

    def get_current_round(self, connection: sqlite3.Connection) -> SimulationRound:
        row = connection.execute(
            """
            SELECT id, day, hour
            FROM rounds
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            raise RuntimeError("No rows found in rounds table")
        return SimulationRound(id=int(row["id"]), day=int(row["day"]), slot=int(row["hour"]))

    def get_rounds_after(
        self,
        connection: sqlite3.Connection,
        after_round_id: int | None,
    ) -> tuple[SimulationRound, ...]:
        if after_round_id is None:
            rows = connection.execute(
                """
                SELECT id, day, hour
                FROM rounds
                ORDER BY id ASC
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, day, hour
                FROM rounds
                WHERE id > ?
                ORDER BY id ASC
                """,
                (after_round_id,),
            ).fetchall()
        return tuple(
            SimulationRound(id=int(row["id"]), day=int(row["day"]), slot=int(row["hour"]))
            for row in rows
        )

    def get_recent_posts(
        self,
        connection: sqlite3.Connection,
        *,
        round_id: int,
        limit: int,
    ) -> tuple[PostRecord, ...]:
        rows = connection.execute(
            """
            SELECT id, user_id, tweet, round, comment_to, thread_id, shared_from
            FROM post
            WHERE round <= ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (round_id, limit),
        ).fetchall()
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

    def get_users(self, connection: sqlite3.Connection) -> tuple[UserRecord, ...]:
        rows = connection.execute(
            """
            SELECT id, username, user_type, owner
            FROM user_mgmt
            ORDER BY id ASC
            """
        ).fetchall()
        return tuple(
            UserRecord(
                id=int(row["id"]),
                username=str(row["username"]),
                user_type=row["user_type"],
                owner=row["owner"],
            )
            for row in rows
        )

    def get_user_id(self, connection: sqlite3.Connection, username: str) -> int:
        row = connection.execute(
            """
            SELECT id
            FROM user_mgmt
            WHERE username = ?
            LIMIT 1
            """,
            (username,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"User '{username}' not found in user_mgmt")
        if isinstance(row, sqlite3.Row):
            return int(row["id"])
        return int(row[0])

    def register_agents(
        self,
        connection: sqlite3.Connection,
        agents: tuple[AgentSpec, ...],
        *,
        joined_on: int,
    ) -> None:
        supported_columns = self._table_columns(connection, "user_mgmt")
        for agent in agents:
            existing = connection.execute(
                """
                SELECT id
                FROM user_mgmt
                WHERE username = ? OR email = ?
                LIMIT 1
                """,
                (agent.username, agent.email),
            ).fetchone()

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
            }
            filtered_values = {
                column: value
                for column, value in values.items()
                if column in supported_columns and value is not None
            }
            columns = tuple(filtered_values.keys())
            params = tuple(filtered_values.values())

            if existing is None:
                placeholders = ", ".join("?" for _ in columns)
                column_sql = ", ".join(columns)
                connection.execute(
                    f"""
                    INSERT INTO user_mgmt ({column_sql})
                    VALUES ({placeholders})
                    """,
                    params,
                )
            else:
                assignments = ", ".join(f"{column} = ?" for column in columns)
                connection.execute(
                    f"""
                    UPDATE user_mgmt
                    SET {assignments}
                    WHERE id = ?
                    """,
                    params + (int(existing["id"]),),
                )

        connection.commit()

    def create_post(
        self,
        connection: sqlite3.Connection,
        *,
        username: str,
        text: str,
        round_id: int,
    ) -> int:
        user_id = self.get_user_id(connection, username)
        cursor = connection.execute(
            """
            INSERT INTO post (tweet, user_id, comment_to, thread_id, round, shared_from)
            VALUES (?, ?, -1, NULL, ?, -1)
            """,
            (text, user_id, round_id),
        )
        connection.commit()
        return int(cursor.lastrowid)

    def count_posts_by_username_and_text(
        self,
        connection: sqlite3.Connection,
        *,
        username: str,
        text: str,
    ) -> int:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM post
            JOIN user_mgmt ON user_mgmt.id = post.user_id
            WHERE user_mgmt.username = ? AND post.tweet = ?
            """,
            (username, text),
        ).fetchone()
        return int(row[0])

    def _table_columns(
        self,
        connection: sqlite3.Connection,
        table_name: str,
    ) -> set[str]:
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        columns = set()
        for row in rows:
            if isinstance(row, sqlite3.Row):
                columns.add(str(row["name"]))
            else:
                columns.add(str(row[1]))
        return columns


def _nullable_int(value: object) -> int | None:
    if value is None:
        return None
    numeric = int(value)
    return None if numeric < 0 else numeric
