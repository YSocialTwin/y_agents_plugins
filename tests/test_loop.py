from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import text

from y_agents_plugins.core import AgentSpec
from y_agents_plugins.db import ExperimentDatabase
from y_agents_plugins.runtime.loop import SimulationLoop


def _build_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE rounds (id INTEGER PRIMARY KEY AUTOINCREMENT, day INTEGER, hour INTEGER);
        CREATE TABLE user_mgmt (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            user_type TEXT,
            owner TEXT
        );
        CREATE TABLE post (
            id INTEGER PRIMARY KEY,
            tweet TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            comment_to INTEGER DEFAULT -1,
            thread_id INTEGER,
            round INTEGER,
            shared_from INTEGER DEFAULT -1
        );
        INSERT INTO rounds (day, hour) VALUES (0, 0);
        INSERT INTO user_mgmt (id, username, user_type, owner) VALUES (1, 'alice', 'human', 'experiment');
        INSERT INTO post (id, tweet, user_id, round) VALUES (1, 'first post', 1, 1);
        INSERT INTO rounds (day, hour) VALUES (0, 1);
        INSERT INTO post (id, tweet, user_id, round) VALUES (2, 'second post', 1, 2);
        """
    )
    connection.commit()
    return connection


def test_simulation_loop_processes_latest_round_once(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    database = ExperimentDatabase(db_path)
    loop = SimulationLoop(
        database=database,
        client_id="test-client",
        recent_posts_limit=10,
        poll_interval_seconds=0.0,
    )
    seen = []

    def handler(context, agent):
        seen.append((context.current_round.day, context.current_round.slot, len(context.recent_posts)))
        return []

    managed_agents = (
        AgentSpec(
            name="Moderator One",
            username="mod_1",
            email="mod_1@example.org",
            password="secret",
            agent_type="moderator",
            activity_profile="Always On",
            daily_budget=42,
        ),
    )

    loop.run(handler, managed_agents=managed_agents, max_ticks=1, connection=database.connect())

    assert seen == [(0, 0, 1)]
    connection.close()


def test_simulation_loop_passes_previous_round_on_second_tick(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    database = ExperimentDatabase(db_path)
    loop = SimulationLoop(
        database=database,
        client_id="test-client",
        recent_posts_limit=10,
        poll_interval_seconds=0.0,
    )
    handler_calls = []
    reader = database.connect()

    managed_agents = (
        AgentSpec(
            name="Moderator One",
            username="mod_1",
            email="mod_1@example.org",
            password="secret",
            agent_type="moderator",
            activity_profile="Always On",
            daily_budget=42,
        ),
    )

    def handler(context, agent):
        handler_calls.append(
            (
                context.current_round.id,
                None if context.previous_round is None else context.previous_round.id,
                agent.username,
            )
        )
        if len(handler_calls) == 1:
            reader.execute(text("INSERT INTO rounds (day, hour) VALUES (0, 2)"))
            reader.execute(
                text("INSERT INTO post (id, tweet, user_id, round) VALUES (3, 'flag this idiot', 1, 3)")
            )
            reader.commit()
        return []

    loop.run(handler, managed_agents=managed_agents, max_ticks=2, connection=reader)

    assert handler_calls == [(1, None, "mod_1"), (2, 1, "mod_1")]
    reader.close()
    connection.close()


def test_simulation_loop_catches_up_all_missed_rounds(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    database = ExperimentDatabase(db_path)
    loop = SimulationLoop(
        database=database,
        client_id="test-client",
        recent_posts_limit=10,
        poll_interval_seconds=0.0,
    )
    connection.execute("INSERT INTO rounds (day, hour) VALUES (0, 2)")
    connection.execute("INSERT INTO rounds (day, hour) VALUES (0, 3)")
    connection.commit()
    seen = []
    managed_agents = (
        AgentSpec(
            name="Moderator One",
            username="mod_1",
            email="mod_1@example.org",
            password="secret",
            agent_type="moderator",
            activity_profile="Always On",
            daily_budget=42,
        ),
    )

    def handler(context, agent):
        seen.append(context.current_round.id)
        return []

    loop.run(
        handler,
        managed_agents=managed_agents,
        max_ticks=3,
        connection=database.connect(),
    )

    assert seen == [1, 2, 3]
    connection.close()


def test_simulation_loop_skips_agent_when_activity_profile_is_inactive(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    database = ExperimentDatabase(db_path)
    seen = []
    managed_agents = (
        AgentSpec(
            name="Night Agent",
            username="night_1",
            email="night_1@example.org",
            password="secret",
            agent_type="moderator",
            activity_profile="Night",
            daily_budget=42,
        ),
    )

    loop = SimulationLoop(
        database=database,
        client_id="test-client",
        recent_posts_limit=10,
        poll_interval_seconds=0.0,
        activity_filter=lambda agent, current_round: agent.activity_profile == "Always On",
    )

    def handler(context, agent):
        seen.append((context.current_round.id, agent.username))
        return []

    loop.run(handler, managed_agents=managed_agents, max_ticks=2, connection=database.connect())

    assert seen == []
    connection.close()
