from __future__ import annotations

import sqlite3
from pathlib import Path

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec, SimulationRound
from y_agents_plugins.db import ExperimentDatabase
from y_agents_plugins.plugins.moderator import ModeratorAgent
from y_agents_plugins.runtime.executor import ActionExecutor


def _build_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE rounds (id INTEGER PRIMARY KEY AUTOINCREMENT, day INTEGER, hour INTEGER);
        CREATE TABLE user_mgmt (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT,
            password TEXT,
            user_type TEXT,
            owner TEXT,
            interests TEXT,
            age INTEGER
        );
        CREATE TABLE post (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            comment_to INTEGER DEFAULT -1,
            thread_id INTEGER,
            round INTEGER,
            shared_from INTEGER DEFAULT -1,
            moderated INTEGER DEFAULT 0
        );
        CREATE TABLE reported (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            to_uid INTEGER,
            to_post INTEGER,
            from_uid INTEGER NOT NULL,
            tid INTEGER NOT NULL
        );
        CREATE TABLE post_toxicity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            toxicity REAL DEFAULT 0 NOT NULL
        );
        CREATE TABLE sys_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            to_uid INTEGER,
            message TEXT NOT NULL,
            from_round INTEGER,
            duration INTEGER
        );
        INSERT INTO rounds (day, hour) VALUES (0, 0);
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner)
        VALUES (1, 'hello_1', 'hello_1@example.org', 'secret', 'moderator', 'experiment');
        """
    )
    connection.commit()
    return connection


def test_executor_persists_post_action(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    database = ExperimentDatabase(db_path)
    executor = ActionExecutor(database)
    sa_connection = database.connect()
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=(),
        recent_posts=(),
        managed_agents=(),
    )
    agent = AgentSpec(
        name="Hello One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="hello_world",
        activity_profile="Always On",
        daily_budget=24,
    )
    action = AgentAction(
        agent_type="hello_world",
        action_type="CREATE_POST",
        payload={"text": "HELLO WORLD"},
    )

    executor.execute(sa_connection, context=context, agent=agent, action=action)
    count = database.count_posts_by_username_and_text(
        sa_connection, username="hello_1", text="HELLO WORLD"
    )

    assert count == 1
    sa_connection.close()
    connection.close()


def test_executor_persists_moderation_action_and_updates_counts(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment')"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (1, 'you are stupid', 2, 1, 0)"
    )
    connection.commit()
    database = ExperimentDatabase(db_path)
    executor = ActionExecutor(database)
    sa_connection = database.connect()
    ModeratorAgent(
        settings={
            "toxicity_threshold": 0.5,
            "moderation_time_span": 3,
            "moderation_action_type": "one-fits-all",
        }
    ).setup_database(database, sa_connection)
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=(),
        recent_posts=(),
        managed_agents=(),
    )
    agent = AgentSpec(
        name="Moderator One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="moderator",
        activity_profile="Always On",
        daily_budget=24,
    )
    action = AgentAction(
        agent_type="moderator",
        action_type="APPLY_MODERATION",
        payload={
            "post_id": 1,
            "target_user_id": 2,
            "reason": "one-fits-all",
            "round_id": 1,
            "message_type": "moderation",
            "message_duration": 3,
            "system_message_text": "Adjust your behavior.",
        },
    )

    executor.execute(sa_connection, context=context, agent=agent, action=action)

    assert database.count_rows(sa_connection, "plugin_moderation_actions") == 1
    assert database.count_rows(sa_connection, "plugin_moderation_counts") == 1
    assert database.count_rows(sa_connection, "sys_messages") == 1
    sa_connection.close()
    connection.close()


def test_moderator_can_generate_personalized_sys_message_and_persist_it(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age) VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'sports', 30)"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (1, 'this is abuse', 2, 1, 0)"
    )
    connection.execute(
        "INSERT INTO reported (type, to_uid, to_post, from_uid, tid) VALUES ('post', 2, 1, 1, 1)"
    )
    connection.execute(
        "INSERT INTO post_toxicity (post_id, toxicity) VALUES (1, 0.8)"
    )
    connection.commit()
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()

    class StubLLM:
        is_available = True

        def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
            assert "moderation assistant" in system_prompt.lower()
            assert "this is abuse" in user_prompt
            return "Your message violated the moderation policy."

    moderator = ModeratorAgent(
        settings={
            "toxicity_threshold": 0.5,
            "moderation_time_span": 3,
            "moderation_action_type": "personalized",
            "candidate_window_rounds": 2,
        },
        llm_client=StubLLM(),
    )
    moderator.setup_database(database, sa_connection)
    executor = ActionExecutor(database)
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=5),
        managed_agents=(),
    )
    agent = AgentSpec(
        name="Moderator One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="moderator",
        activity_profile="Always On",
        daily_budget=24,
    )

    actions = moderator.on_tick(context, agent)
    assert [action.action_type for action in actions] == ["READ", "APPLY_MODERATION"]
    assert actions[1].payload["system_message_text"] == "Your message violated the moderation policy."

    executor.execute(sa_connection, context=context, agent=agent, action=actions[1])

    sys_message = sa_connection.execute(database.table("sys_messages").select()).mappings().first()
    moderated = sa_connection.execute(
        database.table("post").select().where(database.table("post").c.id == 1)
    ).mappings().first()
    assert sys_message["message"] == "Your message violated the moderation policy."
    assert moderated["moderated"] == 1
    sa_connection.close()
    connection.close()
