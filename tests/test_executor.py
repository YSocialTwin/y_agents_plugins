from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import text

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec, SimulationRound
from y_agents_plugins.db import ExperimentDatabase
from y_agents_plugins.plugins.master_of_puppets import MasterOfPuppetsAgent
from y_agents_plugins.plugins.moderator import ModeratorAgent
from y_agents_plugins.plugins.propaganda import PropagandaAgent
from y_agents_plugins.plugins.comic_relief import ComicReliefAgent
from y_agents_plugins.plugins.stress_attacker import StressAttackerAgent
from y_agents_plugins.plugins.hello_world import HelloWorldAgent
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
            age INTEGER,
            leaning TEXT,
            left_on INTEGER
        );
        CREATE TABLE post (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            comment_to INTEGER DEFAULT -1,
            thread_id INTEGER,
            round INTEGER,
            shared_from INTEGER DEFAULT -1,
            moderated INTEGER DEFAULT 0,
            is_moderation_comment INTEGER DEFAULT 0
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
        CREATE TABLE post_topics (
            post_id INTEGER NOT NULL,
            topic_id INTEGER NOT NULL
        );
        CREATE TABLE hashtags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hashtag TEXT NOT NULL
        );
        CREATE TABLE post_hashtags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            hashtag_id INTEGER NOT NULL
        );
        CREATE TABLE mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            round INTEGER NOT NULL,
            answered INTEGER DEFAULT 0
        );
        CREATE TABLE reactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            post_id INTEGER NOT NULL,
            type TEXT NOT NULL
        );
        CREATE TABLE follow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            follower_id INTEGER NOT NULL,
            round INTEGER NOT NULL,
            action TEXT NOT NULL
        );
        CREATE TABLE sys_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            to_uid INTEGER,
            message TEXT NOT NULL,
            from_round INTEGER,
            duration INTEGER
        );
        CREATE TABLE propaganda_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            target_uid INTEGER NOT NULL,
            propaganda_agent_uid INTEGER NOT NULL,
            thread_id INTEGER NOT NULL,
            discussion_round_id INTEGER NOT NULL,
            target_opinion REAL,
            topic_id INTEGER NOT NULL
        );
        CREATE TABLE interests (
            iid INTEGER PRIMARY KEY,
            topic TEXT
        );
        CREATE TABLE agent_opinion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id INTEGER NOT NULL,
            tid INTEGER NOT NULL,
            topic_id INTEGER NOT NULL,
            id_interacted_with INTEGER NOT NULL,
            id_post INTEGER NOT NULL,
            opinion REAL NOT NULL
        );
        CREATE TABLE daily_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            p_id INTEGER NOT NULL,
            timestamp INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            payload TEXT,
            scheduled_time INTEGER NOT NULL,
            schedule_day INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            executed_round_id INTEGER
        );
        CREATE TABLE activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            p_id INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            target_post_id INTEGER,
            status TEXT NOT NULL,
            round_id INTEGER NOT NULL,
            details TEXT
        );
        INSERT INTO rounds (day, hour) VALUES (0, 0);
        INSERT INTO interests (iid, topic) VALUES (1, 'Climate');
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner)
        VALUES (1, 'hello_1', 'hello_1@example.org', 'secret', 'moderator', 'experiment');
        """
    )
    connection.commit()
    return connection


def _build_uuid_hpc_db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE rounds (id VARCHAR(36) PRIMARY KEY, day INTEGER, hour INTEGER);
        CREATE TABLE user_mgmt (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            username TEXT NOT NULL,
            email TEXT,
            password TEXT NOT NULL,
            user_type TEXT,
            owner TEXT,
            interests TEXT,
            age INTEGER,
            leaning TEXT,
            left_on VARCHAR(36),
            round_actions INTEGER NOT NULL,
            is_page INTEGER NOT NULL,
            activity_profile TEXT,
            daily_activity_level INTEGER,
            last_active_day INTEGER
        );
        CREATE TABLE post (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            tweet TEXT NOT NULL,
            user_id VARCHAR(36) NOT NULL,
            comment_to VARCHAR(36),
            thread_id VARCHAR(36),
            round VARCHAR(36),
            shared_from VARCHAR(36),
            moderated INTEGER NOT NULL,
            is_moderation_comment INTEGER NOT NULL
        );
        CREATE TABLE reported (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            type TEXT NOT NULL,
            to_uid VARCHAR(36),
            to_post VARCHAR(36),
            from_uid VARCHAR(36) NOT NULL,
            tid VARCHAR(36) NOT NULL
        );
        CREATE TABLE post_toxicity (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            post_id VARCHAR(36) NOT NULL,
            toxicity REAL DEFAULT 0 NOT NULL
        );
        CREATE TABLE post_topics (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            post_id VARCHAR(36),
            topic_id VARCHAR(36)
        );
        CREATE TABLE hashtags (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            hashtag TEXT NOT NULL
        );
        CREATE TABLE post_hashtags (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            post_id VARCHAR(36),
            hashtag_id VARCHAR(36)
        );
        CREATE TABLE mentions (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            user_id VARCHAR(36),
            post_id VARCHAR(36),
            round VARCHAR(36),
            answered INTEGER DEFAULT 0
        );
        CREATE TABLE reactions (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            round VARCHAR(36),
            user_id VARCHAR(36),
            post_id VARCHAR(36),
            type TEXT
        );
        CREATE TABLE follow (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            user_id VARCHAR(36) NOT NULL,
            follower_id VARCHAR(36) NOT NULL,
            round VARCHAR(36),
            action TEXT
        );
        CREATE TABLE sys_messages (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            type TEXT NOT NULL,
            to_uid VARCHAR(36),
            message TEXT NOT NULL,
            from_round VARCHAR(36),
            duration INTEGER
        );
        CREATE TABLE interests (
            iid VARCHAR(36) PRIMARY KEY NOT NULL,
            topic TEXT
        );
        CREATE TABLE agent_opinion (
            id VARCHAR(36) PRIMARY KEY NOT NULL,
            agent_id VARCHAR(36) NOT NULL,
            tid VARCHAR(36) NOT NULL,
            topic_id VARCHAR(36) NOT NULL,
            id_interacted_with VARCHAR(36),
            id_post VARCHAR(36),
            opinion REAL NOT NULL,
            stubborn INTEGER NOT NULL
        );
        CREATE TABLE daily_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            p_id VARCHAR(36) NOT NULL,
            timestamp INTEGER NOT NULL,
            action_type TEXT NOT NULL,
            payload TEXT,
            scheduled_time INTEGER NOT NULL,
            schedule_day INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            executed_round_id VARCHAR(36)
        );
        CREATE TABLE activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            p_id VARCHAR(36) NOT NULL,
            action_type TEXT NOT NULL,
            target_post_id VARCHAR(36),
            status TEXT NOT NULL,
            round_id INTEGER NOT NULL,
            details TEXT
        );
        INSERT INTO rounds (id, day, hour) VALUES ('round-1', 0, 0);
        INSERT INTO interests (iid, topic) VALUES ('topic-climate', 'Climate');
        INSERT INTO user_mgmt (
            id, username, email, password, user_type, owner, round_actions, is_page, activity_profile, daily_activity_level, last_active_day
        ) VALUES (
            'agent-1', 'hello_1', 'hello_1@example.org', 'secret', 'moderator', 'experiment', 12, 0, 'Always On', 1, 0
        );
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
    actor_id = database.get_user_id(sa_connection, "hello_1")
    row = sa_connection.execute(
        text("SELECT comment_to, thread_id FROM post WHERE user_id = :user_id AND tweet = 'HELLO WORLD'"),
        {"user_id": actor_id},
    ).mappings().first()

    assert count == 1
    assert row is not None
    assert int(row["comment_to"]) == -1
    assert int(row["thread_id"]) > 0
    sa_connection.close()
    connection.close()


def test_hello_world_post_does_not_write_stress_reward(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    database.ensure_stress_reward_schema(sa_connection)
    executor = ActionExecutor(
        database,
        stress_reward_config={"enabled": True, "backward_rounds": 24, "system": {}},
    )
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

    assert database.count_rows(sa_connection, "stress_reward") == 0
    sa_connection.close()
    connection.close()


def test_hello_world_agent_supports_custom_post_text() -> None:
    agent = AgentSpec(
        name="Hello One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="hello_world",
        activity_profile="Always On",
        daily_budget=24,
        parameters={"post_text": "Custom hello"},
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=(),
        recent_posts=(),
        managed_agents=(),
    )

    actions = HelloWorldAgent().on_tick(context, agent)

    assert len(actions) == 1
    assert actions[0].action_type == "CREATE_POST"
    assert actions[0].payload["text"] == "Custom hello"


def test_executor_extracts_mentions_for_plugin_posts_and_comments(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment')"
    )
    connection.commit()
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
        name="Propaganda One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="propaganda",
        activity_profile="Always On",
        daily_budget=24,
    )

    executor.execute(
        sa_connection,
        context=context,
        agent=agent,
        action=AgentAction(
            agent_type="propaganda",
            action_type="CREATE_POST",
            payload={"text": "@target_1 Please reconsider this issue. #HelloWorld"},
        ),
    )
    created_post_id = sa_connection.execute(text("select max(id) from post")).scalar_one()
    mentions = sa_connection.execute(
        text("select user_id, post_id, round, answered from mentions order by id")
    ).fetchall()
    assert mentions == [(2, created_post_id, 1, 0)]
    topics = sa_connection.execute(
        text("select post_id, topic_id from post_topics order by topic_id")
    ).fetchall()
    assert topics == []

    executor.execute(
        sa_connection,
        context=context,
        agent=agent,
        action=AgentAction(
            agent_type="propaganda",
            action_type="CREATE_COMMENT",
            payload={
                "text": "@target_1 Here is a follow-up thought. #ReplyTag",
                "parent_post_id": int(created_post_id),
            },
        ),
    )
    comment_mentions = sa_connection.execute(
        text("select count(*) from mentions where post_id != :post_id"),
        {"post_id": int(created_post_id)},
    ).scalar_one()
    assert comment_mentions == 1
    created_comment_id = sa_connection.execute(text("select max(id) from post")).scalar_one()
    hashtags = sa_connection.execute(
        text(
            "select h.hashtag, ph.post_id from hashtags h join post_hashtags ph on ph.hashtag_id = h.id order by ph.post_id, h.hashtag"
        )
    ).fetchall()
    assert hashtags == [("HelloWorld", created_post_id), ("ReplyTag", created_comment_id)]
    sa_connection.close()
    connection.close()


def test_executor_skips_duplicate_comment_on_same_parent_for_same_actor(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment')"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment) "
        "VALUES (1, 'Target post', 2, -1, 1, 1, -1, 0, 0)"
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    executor = ActionExecutor(database)
    sa_connection = database.connect()
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=10),
        managed_agents=(),
    )
    agent = AgentSpec(
        name="Stress One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="stress_attacker",
        activity_profile="Always On",
        daily_budget=24,
    )
    action = AgentAction(
        agent_type="stress_attacker",
        action_type="CREATE_COMMENT",
        payload={"text": "@target_1 first reply", "parent_post_id": 1},
    )

    executor.execute(sa_connection, context=context, agent=agent, action=action)
    executor.execute(sa_connection, context=context, agent=agent, action=action)

    assert sa_connection.execute(
        text("select count(*) from post where comment_to = 1 and user_id = 1")
    ).scalar_one() == 1
    sa_connection.close()
    connection.close()


def test_executor_persists_propaganda_topic_ids_on_posts(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment')"
    )
    connection.commit()
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
        name="Propaganda One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="propaganda",
        activity_profile="Always On",
        daily_budget=24,
    )
    executor.execute(
        sa_connection,
        context=context,
        agent=agent,
        action=AgentAction(
            agent_type="propaganda",
            action_type="CREATE_POST",
            payload={
                "text": "@target_1 Let us discuss climate.",
                "propaganda_activity": {
                    "target_uid": 2,
                    "topic_id": 1,
                    "target_opinion": 0.1,
                    "discussion_round_id": 1,
                },
            },
        ),
    )

    assert sa_connection.execute(
        text("select post_id, topic_id from post_topics order by post_id, topic_id")
    ).fetchall() == [(1, 1)]
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
    moderation_comment = sa_connection.execute(
        database.table("post").select().where(database.table("post").c.id != 1)
    ).mappings().first()
    assert moderation_comment["tweet"] == "Adjust your behavior."
    assert moderation_comment["comment_to"] == 1
    assert moderation_comment["is_moderation_comment"] == 1
    sa_connection.close()
    connection.close()


def test_executor_persists_stress_reward_for_moderation_target(tmp_path: Path) -> None:
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
    sa_connection = database.connect()
    database.ensure_stress_reward_schema(sa_connection)
    executor = ActionExecutor(
        database,
        stress_reward_config={"enabled": True, "backward_rounds": 24, "system": {}},
    )
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
            "stress_reward": {"outcome": "sanctioned", "action": "moderation:sanctioned"},
        },
    )

    executor.execute(sa_connection, context=context, agent=agent, action=action)

    rows = sa_connection.execute(
        text(
            "select uid, variable, type, action from stress_reward order by type asc, variable asc"
        )
    ).fetchall()
    assert rows == [
        (2, "reward", "aggregate", None),
        (2, "stress", "aggregate", None),
        (2, "reward", "variation", "moderation:sanctioned"),
        (2, "stress", "variation", "moderation:sanctioned"),
    ]
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
    moderation_comment = sa_connection.execute(
        database.table("post").select().where(database.table("post").c.id != 1).order_by(database.table("post").c.id.desc())
    ).mappings().first()
    assert sys_message["message"] == "Your message violated the moderation policy."
    assert moderated["moderated"] == 1
    assert moderation_comment["tweet"] == "Your message violated the moderation policy."
    assert moderation_comment["comment_to"] == 1
    sa_connection.close()
    connection.close()


def test_propaganda_agent_starts_thread_and_records_activity(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age) VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'climate', 30)"
    )
    connection.execute(
        "INSERT INTO agent_opinion (agent_id, tid, topic_id, id_interacted_with, id_post, opinion) VALUES (2, 1, 1, 2, 0, 0.10)"
    )
    connection.commit()

    class StubLLM:
        is_available = True

        def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
            assert system_prompt == "OPENING OVERRIDE"
            assert "avoid toxicity" in user_prompt.lower()
            assert "target_1" in user_prompt
            return '"target_1@ysocial.it you may be underestimating the benefits of climate action."'

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    PropagandaAgent(
        settings={
            "propaganda_campaigns": [
                {
                    "topic_id": 99,
                    "topic_name": "Climate",
                    "target_opinion": 0.9,
                    "target_agent_opinion_group": "Opposed",
                    "target_agent_opinion_group_bounds": {
                        "name": "Opposed",
                        "lower_bound": 0.0,
                        "upper_bound": 0.2,
                        "value": 0.1,
                    },
                }
            ],
            "epsilon": 0.05,
            "max_interaction_rounds": 4,
            "opening_llm_prompt_override": "OPENING OVERRIDE",
        },
        llm_client=StubLLM(),
    ).setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Propaganda One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="propaganda",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=5),
        managed_agents=(agent,),
        connection=sa_connection,
    )
    propaganda = PropagandaAgent(
        settings={
            "propaganda_campaigns": [
                {
                    "topic_id": 99,
                    "topic_name": "Climate",
                    "target_opinion": 0.9,
                    "target_agent_opinion_group": "Opposed",
                    "target_agent_opinion_group_bounds": {
                        "name": "Opposed",
                        "lower_bound": 0.0,
                        "upper_bound": 0.2,
                        "value": 0.1,
                    },
                }
            ],
            "epsilon": 0.05,
            "max_interaction_rounds": 4,
            "opening_llm_prompt_override": "OPENING OVERRIDE",
        },
        llm_client=StubLLM(),
    )
    propaganda.setup_database(database, sa_connection)
    actions = propaganda.on_tick(context, agent)

    assert [action.action_type for action in actions] == ["READ", "CREATE_POST"]
    assert database.get_latest_agent_opinion(
        sa_connection,
        user_id=1,
        topic_id=1,
        current_round_id=1,
    ) == 0.9

    executor = ActionExecutor(database)
    executor.execute(sa_connection, context=context, agent=agent, action=actions[1])

    post = sa_connection.execute(
        text("SELECT id, tweet FROM post WHERE id = 1 ORDER BY id DESC")
    ).fetchone()
    activity = sa_connection.execute(
        text(
            "SELECT target_uid, propaganda_agent_uid, thread_id, discussion_round_id, target_opinion, topic_id "
            "FROM propaganda_activity ORDER BY id DESC LIMIT 1"
        )
    ).fetchone()

    assert post is not None
    assert post[1].startswith("@target_1 ")
    assert activity == (2, 1, 1, 1, 0.1, 1)
    sa_connection.close()
    connection.close()


def test_executor_persists_stress_reward_for_directed_propaganda_post(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment')"
    )
    connection.commit()
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    database.ensure_stress_reward_schema(sa_connection)
    executor = ActionExecutor(
        database,
        stress_reward_config={"enabled": True, "backward_rounds": 24, "system": {}},
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=(),
        managed_agents=(),
    )
    agent = AgentSpec(
        name="Propaganda One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="propaganda",
        activity_profile="Always On",
        daily_budget=24,
    )
    action = AgentAction(
        agent_type="propaganda",
        action_type="CREATE_POST",
        payload={
            "text": "@target_1 Please reconsider this issue.",
            "stress_reward": {"tone": "positive", "action": "post:positive", "target_user_id": 2},
            "propaganda_activity": {
                "target_uid": 2,
                "topic_id": 1,
                "target_opinion": 0.1,
                "discussion_round_id": 1,
            },
        },
    )

    executor.execute(sa_connection, context=context, agent=agent, action=action)

    rows = sa_connection.execute(
        text("select uid, variable, type, action from stress_reward order by type asc, variable asc")
    ).fetchall()
    assert rows == [
        (2, "reward", "aggregate", None),
        (2, "stress", "aggregate", None),
        (2, "reward", "variation", "post:positive"),
        (2, "stress", "variation", "post:positive"),
    ]
    sa_connection.close()
    connection.close()


def test_set_fixed_agent_opinion_supports_uuid_topic_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation_uuid.db"
    connection = _build_uuid_hpc_db(db_path)
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()

    changed = database.set_fixed_agent_opinion(
        sa_connection,
        user_id="agent-1",
        topic_id="topic-climate",
        opinion=0.75,
        round_id="round-1",
    )

    row = sa_connection.execute(
        text(
            "SELECT id, agent_id, topic_id, opinion, stubborn "
            "FROM agent_opinion ORDER BY rowid DESC LIMIT 1"
        )
    ).fetchone()
    assert changed is True
    assert row is not None
    assert row[0]
    assert row[1:] == ("agent-1", "topic-climate", 0.75, 0)
    sa_connection.close()
    connection.close()


def test_propaganda_agent_supports_uuid_topic_ids_on_hpc_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation_uuid.db"
    connection = _build_uuid_hpc_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner, round_actions, is_page, activity_profile, daily_activity_level, last_active_day, interests, age) "
        "VALUES ('target-1', 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 8, 0, 'Always On', 1, 0, 'climate', 30)"
    )
    connection.execute(
        "INSERT INTO agent_opinion (id, agent_id, tid, topic_id, id_interacted_with, id_post, opinion, stubborn) "
        "VALUES ('op-1', 'target-1', 'round-1', 'topic-climate', NULL, NULL, 0.10, 0)"
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    propaganda = PropagandaAgent(
        settings={
            "propaganda_campaigns": [
                {
                    "topic_id": "topic-climate",
                    "topic_name": "Climate",
                    "target_opinion": 0.9,
                    "target_agent_opinion_group": "Opposed",
                    "target_agent_opinion_group_bounds": {
                        "name": "Opposed",
                        "lower_bound": 0.0,
                        "upper_bound": 0.2,
                        "value": 0.1,
                    },
                }
            ],
            "epsilon": 0.05,
            "max_interaction_rounds": 4,
        }
    )
    propaganda.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Propaganda One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="propaganda",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id="round-1", day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id="round-1", limit=5),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = propaganda.on_tick(context, agent)
    assert [action.action_type for action in actions] == ["READ", "CREATE_POST"]
    assert actions[1].payload["topic_ids"] == ["topic-climate"]

    executor = ActionExecutor(database)
    executor.execute(sa_connection, context=context, agent=agent, action=actions[1])

    post_topics = sa_connection.execute(
        text("SELECT topic_id FROM post_topics ORDER BY rowid DESC LIMIT 1")
    ).fetchone()
    activity = sa_connection.execute(
        text("SELECT topic_id FROM propaganda_activity ORDER BY id DESC LIMIT 1")
    ).fetchone()
    own_opinion = sa_connection.execute(
        text(
            "SELECT topic_id, opinion FROM agent_opinion "
            "WHERE agent_id = 'agent-1' ORDER BY rowid DESC LIMIT 1"
        )
    ).fetchone()

    assert post_topics == ("topic-climate",)
    assert activity == ("topic-climate",)
    assert own_opinion == ("topic-climate", 0.9)
    sa_connection.close()
    connection.close()


def test_stress_attacker_selects_target_and_emits_safe_synthetic_actions(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner, age, leaning, interests) "
        "VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 54, 'democrat', 'climate,education')"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment) "
        "VALUES (1, 'A recent post', 2, -1, NULL, 1, -1, 0, 0)"
    )
    connection.execute(
        "INSERT INTO post_topics (post_id, topic_id) VALUES (1, 1)"
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    attacker = StressAttackerAgent(
        settings={
            "target_min_age": 50,
            "target_max_age": 60,
            "target_leaning": "democrat",
            "negative_reactions_enabled": "enabled",
            "critical_comment_enabled": "enabled",
            "critical_comment_mode": "synthetic",
            "critical_comment_text": "Please explain the weakest part of your reasoning.",
            "report_burst_enabled": "enabled",
            "source_count": 2,
        }
    )
    attacker.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Stress One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="stress_attacker",
        activity_profile="Always On",
        daily_budget=12,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=10),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = attacker.on_tick(context, agent)

    assert [action.action_type for action in actions] == [
        "READ",
        "APPLY_STRESS_EVENT",
        "CREATE_COMMENT",
        "REPORT_POST",
        "APPLY_STRESS_EVENT",
    ]
    assert actions[2].payload["text"] == (
        "@target_1 Please explain the weakest part of your reasoning."
    )
    assert actions[2].payload["topic_ids"] == [1]
    assert all(
        action.payload.get("target_user_id") == 2
        for action in actions[1:]
        if "target_user_id" in action.payload
    )
    sa_connection.close()
    connection.close()


def test_stress_attacker_can_generate_llm_critical_comment(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner, age, leaning, interests) "
        "VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 54, 'democrat', 'climate,education')"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment) "
        "VALUES (1, 'A recent post', 2, -1, NULL, 1, -1, 0, 0)"
    )
    connection.execute(
        "INSERT INTO post_topics (post_id, topic_id) VALUES (1, 1)"
    )
    connection.commit()

    class StubLLM:
        is_available = True

        def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
            assert system_prompt == "OVERRIDE PROMPT"
            assert "@target_1" in user_prompt
            assert "Topic labels: Climate" in user_prompt
            assert "Visible thread context:" in user_prompt
            assert "@target_1: A recent post" in user_prompt
            return "\"@target_1 I don't see evidence for that conclusion.\""

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    attacker = StressAttackerAgent(
        settings={
            "target_filters": [{"feature": "leaning", "value": "democrat"}],
            "negative_reactions_enabled": "disabled",
            "critical_comment_enabled": "enabled",
            "critical_comment_mode": "llm",
            "report_burst_enabled": "disabled",
            "llm_prompt_override": "OVERRIDE PROMPT",
        },
        llm_client=StubLLM(),
    )
    attacker.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Stress One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="stress_attacker",
        activity_profile="Always On",
        daily_budget=12,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=10),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = attacker.on_tick(context, agent)

    assert [action.action_type for action in actions] == ["READ", "CREATE_COMMENT"]
    assert actions[1].payload["parent_post_id"] == 1
    assert actions[1].payload["text"].startswith("@target_1 ")
    assert actions[1].payload["text"] == "@target_1 I don't see evidence for that conclusion."
    assert actions[1].payload["topic_ids"] == [1]
    assert actions[1].payload["stress_reward"]["tone"] == "hostile"
    sa_connection.close()
    connection.close()


def test_stress_attacker_does_not_target_other_adhoc_agents(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner, age, leaning, interests)
        VALUES
            (2, 'comic_1', 'comic_1@example.org', 'secret', 'comic_relief', 'experiment', 30, 'democrat', 'climate'),
            (3, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 31, 'democrat', 'climate');
        INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment)
        VALUES
            (1, 'Plugin authored post', 2, -1, NULL, 1, -1, 0, 0),
            (2, 'Human authored post', 3, -1, NULL, 1, -1, 0, 0);
        INSERT INTO post_topics (post_id, topic_id) VALUES (2, 1);
        """
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    attacker = StressAttackerAgent(
        settings={
            "target_leaning": "democrat",
            "negative_reactions_enabled": "disabled",
            "critical_comment_enabled": "enabled",
            "critical_comment_mode": "synthetic",
            "report_burst_enabled": "disabled",
        }
    )
    attacker.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Stress One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="stress_attacker",
        activity_profile="Always On",
        daily_budget=12,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=10),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = attacker.on_tick(context, agent)

    assert [action.action_type for action in actions] == ["READ", "CREATE_COMMENT"]
    assert actions[1].payload["parent_post_id"] == 2
    assert "@target_1" in actions[1].payload["text"]
    sa_connection.close()
    connection.close()


def test_personalized_moderator_passes_prompt_customization_to_llm(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) "
        "VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment')"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment) "
        "VALUES (1, 'Problematic post', 2, -1, NULL, 1, -1, 0, 0)"
    )
    connection.execute(
        "INSERT INTO post_toxicity (post_id, toxicity) VALUES (1, 0.9)"
    )
    connection.commit()

    class StubLLM:
        is_available = True

        def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
            assert system_prompt == "CUSTOM MOD PROMPT"
            return "Please adjust your behavior."

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    moderator = ModeratorAgent(
        settings={
            "toxicity_threshold": 0.8,
            "moderation_time_span": 4,
            "moderation_action_type": "personalized",
            "candidate_window_rounds": 3,
            "llm_prompt_override": "CUSTOM MOD PROMPT",
        },
        llm_client=StubLLM(),
    )
    moderator.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Moderator One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="moderator",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=10),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = moderator.on_tick(context, agent)

    assert actions[1].payload["system_message_text"] == "Please adjust your behavior."
    sa_connection.close()
    connection.close()


def test_executor_persists_llm_generated_stress_attacker_comment(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) "
        "VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment')"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment) "
        "VALUES (1, 'Target post', 2, -1, NULL, 1, -1, 0, 0)"
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    database.ensure_stress_reward_schema(sa_connection)
    executor = ActionExecutor(
        database,
        stress_reward_config={"enabled": True, "backward_rounds": 24, "system": {}},
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=(),
        managed_agents=(),
    )
    agent = AgentSpec(
        name="Stress One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="stress_attacker",
        activity_profile="Always On",
        daily_budget=12,
    )
    action = AgentAction(
        agent_type="stress_attacker",
        action_type="CREATE_COMMENT",
        payload={
            "parent_post_id": 1,
            "thread_id": 1,
            "text": "@target_1 I don't think your argument is supported here.",
            "stress_reward": {
                "tone": "hostile",
                "action": "comment:hostile",
                "public_exposure": 1.0,
            },
        },
    )

    executor.execute(sa_connection, context=context, agent=agent, action=action)

    comment = sa_connection.execute(
        text("SELECT tweet, comment_to, thread_id FROM post WHERE id = 2")
    ).fetchone()
    stress_rows = sa_connection.execute(
        text("SELECT variable, type, action FROM stress_reward ORDER BY type ASC, variable ASC")
    ).fetchall()

    assert comment == ("@target_1 I don't think your argument is supported here.", 1, 1)
    assert ("stress", "variation", "comment:hostile") in stress_rows
    sa_connection.close()
    connection.close()


def test_executor_infers_comment_exposure_from_thread_size(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) "
        "VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment')"
    )
    connection.executescript(
        """
        INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment)
        VALUES (1, 'Root post', 2, -1, NULL, 1, -1, 0, 0);
        INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment)
        VALUES (2, 'Reply one', 2, 1, 1, 1, -1, 0, 0);
        INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment)
        VALUES (3, 'Reply two', 2, 1, 1, 1, -1, 0, 0);
        """
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    database.ensure_stress_reward_schema(sa_connection)
    executor = ActionExecutor(
        database,
        stress_reward_config={"enabled": True, "backward_rounds": 24, "system": {}},
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=(),
        managed_agents=(),
    )
    agent = AgentSpec(
        name="Stress One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="stress_attacker",
        activity_profile="Always On",
        daily_budget=12,
    )
    action = AgentAction(
        agent_type="stress_attacker",
        action_type="CREATE_COMMENT",
        payload={
            "parent_post_id": 2,
            "thread_id": 1,
            "text": "@target_1 Please clarify the weakest part of this argument.",
            "stress_reward": {
                "tone": "hostile",
                "action": "comment:hostile",
            },
        },
    )

    executor.execute(sa_connection, context=context, agent=agent, action=action)

    stress_value = sa_connection.execute(
        text(
            "SELECT value FROM stress_reward WHERE variable='stress' AND type='variation' AND action='comment:hostile'"
        )
    ).scalar_one()

    assert stress_value > 0.10
    sa_connection.close()
    connection.close()


def test_executor_inherits_parent_topics_for_generic_comments(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) "
        "VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment')"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment) "
        "VALUES (1, 'Root post', 2, -1, NULL, 1, -1, 0, 0)"
    )
    connection.execute(
        "INSERT INTO post_topics (post_id, topic_id) VALUES (1, 1)"
    )
    connection.commit()

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
        name="Comic One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="comic_relief",
        activity_profile="Always On",
        daily_budget=12,
    )

    executor.execute(
        sa_connection,
        context=context,
        agent=agent,
        action=AgentAction(
            agent_type="comic_relief",
            action_type="CREATE_COMMENT",
            payload={
                "parent_post_id": 1,
                "text": "@target_1 That take landed like a PowerPoint in a thunderstorm.",
            },
        ),
    )

    assert sa_connection.execute(
        text("SELECT thread_id FROM post WHERE id = 2")
    ).scalar_one() == 1
    assert sa_connection.execute(
        text("SELECT topic_id FROM post_topics WHERE post_id = 2")
    ).scalar_one() == 1
    sa_connection.close()
    connection.close()


def test_executor_persists_synthetic_stress_attacker_events(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) "
        "VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment')"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment) "
        "VALUES (1, 'Target post', 2, -1, NULL, 1, -1, 0, 0)"
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    database.ensure_stress_reward_schema(sa_connection)
    executor = ActionExecutor(
        database,
        stress_reward_config={"enabled": True, "backward_rounds": 24, "system": {}},
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=(),
        managed_agents=(),
    )
    agent = AgentSpec(
        name="Stress One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="stress_attacker",
        activity_profile="Always On",
        daily_budget=12,
    )
    actions = [
        AgentAction(
            agent_type="stress_attacker",
            action_type="REPORT_POST",
            payload={
                "post_id": 1,
                "target_user_id": 2,
                "source_count": 3,
                "action_name": "report:pressure",
            },
        ),
        AgentAction(
            agent_type="stress_attacker",
            action_type="APPLY_STRESS_EVENT",
            payload={
                "target_user_id": 2,
                "family": "report",
                "subtype": "mass_report",
                "action_name": "report:pressure",
                "volume": 3,
            },
        ),
    ]

    for action in actions:
        executor.execute(sa_connection, context=context, agent=agent, action=action)

    reports_count = sa_connection.execute(text("SELECT COUNT(*) FROM reported")).scalar_one()
    stress_rows = sa_connection.execute(
        text("SELECT variable, type, action FROM stress_reward ORDER BY type ASC, variable ASC, action ASC")
    ).fetchall()

    assert reports_count == 3
    assert ("stress", "variation", "report:pressure") in stress_rows
    sa_connection.close()
    connection.close()


def test_moderator_one_fits_all_can_override_standard_message(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) "
        "VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment')"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment) "
        "VALUES (1, 'Problematic post', 2, -1, NULL, 1, -1, 0, 0)"
    )
    connection.execute(
        "INSERT INTO post_toxicity (post_id, toxicity) VALUES (1, 0.9)"
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    moderator = ModeratorAgent(
        settings={
            "toxicity_threshold": 0.8,
            "moderation_time_span": 4,
            "moderation_action_type": "one-fits-all",
            "candidate_window_rounds": 3,
            "standard_message": "This content breaks the platform rules. Edit it before posting again.",
        },
    )
    moderator.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Moderator One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="moderator",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=10),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = moderator.on_tick(context, agent)

    assert actions[1].payload["system_message_text"] == (
        "This content breaks the platform rules. Edit it before posting again."
    )
    sa_connection.close()
    connection.close()


def test_executor_skips_stress_reward_for_mop_puppet_targets(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) VALUES (2, 'mop_a', 'mop_a@example.org', 'secret', 'mop_puppet', 'mop_1')"
    )
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) VALUES (3, 'mop_b', 'mop_b@example.org', 'secret', 'mop_puppet', 'mop_1')"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, round) VALUES (1, 'boost me', 2, 1)"
    )
    connection.commit()
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    database.ensure_stress_reward_schema(sa_connection)
    executor = ActionExecutor(
        database,
        stress_reward_config={"enabled": True, "backward_rounds": 24, "system": {}},
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=5),
        managed_agents=(),
    )
    agent = AgentSpec(
        name="MoP",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="master_of_puppets",
        activity_profile="Always On",
        daily_budget=24,
    )
    action = AgentAction(
        agent_type="master_of_puppets",
        action_type="REACT_POST",
        payload={
            "acting_username": "mop_b",
            "post_id": 1,
            "reaction_type": "like",
            "stress_reward": {"action": "reaction:like"},
        },
    )

    executor.execute(sa_connection, context=context, agent=agent, action=action)

    assert database.count_rows(sa_connection, "stress_reward") == 0
    sa_connection.close()
    connection.close()


def test_propaganda_agent_strips_meta_wrapper_from_llm_output(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age) VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'sports', 30)"
    )
    connection.execute(
        "INSERT INTO agent_opinion (agent_id, tid, topic_id, id_interacted_with, id_post, opinion) VALUES (2, 1, 1, 2, 0, 0.2)"
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()

    class StubLLM:
        is_available = True

        def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
            return 'Here is a potential post: "@target_1 We should think more carefully about climate policy."'

    propaganda = PropagandaAgent(
        settings={
            "propaganda_campaigns": [
                {
                    "topic_id": 1,
                    "topic_name": "climate",
                    "target_opinion": 0.9,
                }
            ]
        },
        llm_client=StubLLM(),
    )
    propaganda.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Propaganda One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="propaganda",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=5),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = propaganda.on_tick(context, agent)
    create_post = next(action for action in actions if action.action_type == "CREATE_POST")

    assert create_post.payload["text"] == "@target_1 We should think more carefully about climate policy."
    sa_connection.close()
    connection.close()


def test_propaganda_agent_reasserts_fixed_opinion_if_it_drifted(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age)
        VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'climate', 30);
        INSERT INTO agent_opinion (agent_id, tid, topic_id, id_interacted_with, id_post, opinion)
        VALUES (1, 1, 1, -1, -1, 0.25);
        INSERT INTO agent_opinion (agent_id, tid, topic_id, id_interacted_with, id_post, opinion)
        VALUES (2, 1, 1, 2, 0, 0.10);
        """
    )
    connection.commit()

    class StubLLM:
        is_available = True

        def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
            return "@target_1 climate action helps long-term stability."

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    propaganda = PropagandaAgent(
        settings={
            "propaganda_campaigns": [
                {
                    "topic_id": 1,
                    "topic_name": "Climate",
                    "target_opinion": 0.9,
                    "target_agent_opinion_group": "Opposed",
                    "target_agent_opinion_group_bounds": {
                        "name": "Opposed",
                        "lower_bound": 0.0,
                        "upper_bound": 0.2,
                        "value": 0.1,
                    },
                }
            ],
        },
        llm_client=StubLLM(),
    )
    propaganda.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Propaganda One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="propaganda",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=2, day=0, slot=1),
        previous_round=SimulationRound(id=1, day=0, slot=0),
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=2, limit=5),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    propaganda.on_tick(context, agent)

    latest = sa_connection.execute(
        text(
            "SELECT tid, opinion FROM agent_opinion WHERE agent_id = 1 AND topic_id = 1 "
            "ORDER BY id DESC LIMIT 1"
        )
    ).fetchone()
    assert latest == (2, 0.9)
    sa_connection.close()
    connection.close()


def test_propaganda_agent_replies_and_tracks_updated_opinion(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age)
        VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'climate', 30);
        INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from)
        VALUES (1, '@target_1 opening nudge', 1, -1, NULL, 1, -1);
        INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from)
        VALUES (2, '@hello_1 I am not convinced yet', 2, 1, 1, 2, -1);
        INSERT INTO agent_opinion (agent_id, tid, topic_id, id_interacted_with, id_post, opinion)
        VALUES (2, 1, 1, 2, 1, 0.10);
        INSERT INTO agent_opinion (agent_id, tid, topic_id, id_interacted_with, id_post, opinion)
        VALUES (2, 2, 1, 1, 2, 0.35);
        INSERT INTO rounds (day, hour) VALUES (0, 1);
        """
    )
    connection.commit()

    class StubLLM:
        is_available = True

        def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
            assert system_prompt == "REPLY OVERRIDE"
            assert "observed opinion shift" in user_prompt.lower()
            assert "avoid toxicity" in user_prompt.lower()
            return "@target_1 consider how that evidence changes the climate trade-off."

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    propaganda = PropagandaAgent(
        settings={
            "propaganda_campaigns": [
                {
                    "topic_id": 1,
                    "topic_name": "Climate",
                    "target_opinion": 0.9,
                    "target_agent_opinion_group": "Opposed",
                    "target_agent_opinion_group_bounds": {
                        "name": "Opposed",
                        "lower_bound": 0.0,
                        "upper_bound": 0.2,
                        "value": 0.1,
                    },
                }
            ],
            "epsilon": 0.05,
            "max_interaction_rounds": 4,
            "reply_llm_prompt_override": "REPLY OVERRIDE",
        },
        llm_client=StubLLM(),
    )
    propaganda.setup_database(database, sa_connection)
    database.insert_propaganda_activity(
        sa_connection,
        target_uid=2,
        propaganda_agent_uid=1,
        thread_id=1,
        discussion_round_id=1,
        target_opinion=0.10,
        topic_id=1,
    )
    agent = AgentSpec(
        name="Propaganda One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="propaganda",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=2, day=0, slot=1),
        previous_round=SimulationRound(id=1, day=0, slot=0),
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=2, limit=10),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = propaganda.on_tick(context, agent)

    assert [action.action_type for action in actions] == ["READ", "CREATE_COMMENT"]
    assert actions[1].payload["parent_post_id"] == 2

    executor = ActionExecutor(database)
    executor.execute(sa_connection, context=context, agent=agent, action=actions[1])

    reply = sa_connection.execute(
        text("SELECT tweet, comment_to, thread_id FROM post WHERE id = 3")
    ).fetchone()
    activity = sa_connection.execute(
        text(
            "SELECT target_uid, thread_id, discussion_round_id, target_opinion, topic_id "
            "FROM propaganda_activity ORDER BY id DESC LIMIT 1"
        )
    ).fetchone()

    assert "@target_1" in reply[0]
    assert reply[1:] == (2, 1)
    assert activity == (2, 1, 2, 0.35, 1)
    sa_connection.close()
    connection.close()


def test_comic_relief_agent_generates_tagged_post_with_opening_override(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age, leaning) "
        "VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'science,climate', 30, 'democrat')"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment) "
        "VALUES (1, 'I am trying to explain renewable energy policy.', 2, -1, NULL, 1, -1, 0, 0)"
    )
    connection.commit()

    class StubLLM:
        is_available = True

        def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
            assert system_prompt == "OPENING COMIC OVERRIDE"
            assert "dad_jokes" in user_prompt
            assert "science_geek" in user_prompt
            assert "renewable energy policy" in user_prompt
            return "@target_1 That policy thread has the energy of a solar panel trying stand-up."

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    comic = ComicReliefAgent(
        settings={
            "humor_styles": ["dad_jokes", "science_geek"],
            "delivery_mode": "post_only",
            "post_lookback_rounds": 24,
            "opening_llm_prompt_override": "OPENING COMIC OVERRIDE",
        },
        llm_client=StubLLM(),
    )
    comic.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Comic One",
        username="comic_1",
        email="comic_1@example.org",
        password="secret",
        agent_type="comic_relief",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="comic-client",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=10),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = comic.on_tick(context, agent)

    assert [action.action_type for action in actions] == ["READ", "CREATE_POST"]
    assert actions[1].payload["text"].startswith("@target_1 ")
    assert actions[1].payload["stress_reward"]["action"] == "post:supportive"
    sa_connection.close()
    connection.close()


def test_comic_relief_agent_generates_tagged_comment_with_reply_override(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age, leaning) "
        "VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'gaming,fantasy', 28, 'neutral')"
    )
    connection.execute(
        "INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment) "
        "VALUES (1, 'My dragon build keeps collapsing at the final boss.', 2, -1, NULL, 2, -1, 0, 0)"
    )
    connection.commit()

    class StubLLM:
        is_available = True

        def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
            assert system_prompt == "REPLY COMIC OVERRIDE"
            assert "fantasy_gaming" in user_prompt
            assert "dragon build" in user_prompt
            return "Your dragon build sounds like it respecced into interpretive dance."

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    comic = ComicReliefAgent(
        settings={
            "humor_styles": ["fantasy_gaming"],
            "delivery_mode": "comment_only",
            "post_lookback_rounds": 24,
            "reply_llm_prompt_override": "REPLY COMIC OVERRIDE",
        },
        llm_client=StubLLM(),
    )
    comic.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Comic One",
        username="comic_1",
        email="comic_1@example.org",
        password="secret",
        agent_type="comic_relief",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="comic-client",
        current_round=SimulationRound(id=2, day=0, slot=1),
        previous_round=SimulationRound(id=1, day=0, slot=0),
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=2, limit=10),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = comic.on_tick(context, agent)

    assert [action.action_type for action in actions] == ["READ", "CREATE_COMMENT"]
    assert actions[1].payload["parent_post_id"] == 1
    assert actions[1].payload["text"].startswith("@target_1 ")
    assert actions[1].payload["stress_reward"]["action"] == "comment:supportive"
    sa_connection.close()
    connection.close()


def test_comic_relief_ignores_plugin_targets_and_duplicate_parent_comments(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age, leaning)
        VALUES
            (2, 'comic_target', 'comic_target@example.org', 'secret', 'comic_relief', 'experiment', 'gaming', 28, 'neutral'),
            (3, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'gaming', 28, 'neutral'),
            (4, 'comic_1', 'comic_1@example.org', 'secret', 'comic_relief', 'experiment', 'gaming', 28, 'neutral');
        INSERT INTO post (id, tweet, user_id, comment_to, thread_id, round, shared_from, moderated, is_moderation_comment)
        VALUES
            (1, 'Plugin joke bait', 2, -1, NULL, 2, -1, 0, 0),
            (2, 'Human dragon build', 3, -1, NULL, 2, -1, 0, 0),
            (3, '@target_1 existing reply', 4, 2, 2, 2, -1, 0, 0);
        """
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    comic = ComicReliefAgent(
        settings={
            "humor_styles": ["fantasy_gaming"],
            "delivery_mode": "comment_only",
            "post_lookback_rounds": 24,
        },
        llm_client=_FakeLLM(),
    )
    comic.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Comic One",
        username="comic_1",
        email="comic_1@example.org",
        password="secret",
        agent_type="comic_relief",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="comic-client",
        current_round=SimulationRound(id=2, day=0, slot=1),
        previous_round=SimulationRound(id=1, day=0, slot=0),
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=2, limit=10),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = comic.on_tick(context, agent)

    assert [action.action_type for action in actions] == ["READ"]
    sa_connection.close()
    connection.close()


def test_propaganda_agent_can_open_multiple_filtered_targets_up_to_capacity(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age, leaning)
        VALUES
            (2, 'target_left_young_1', 'a@example.org', 'secret', 'human', 'experiment', 'climate', 22, 'Left'),
            (3, 'target_left_young_2', 'b@example.org', 'secret', 'human', 'experiment', 'climate', 24, 'Left'),
            (4, 'target_right_old', 'c@example.org', 'secret', 'human', 'experiment', 'climate', 55, 'Right');
        INSERT INTO agent_opinion (agent_id, tid, topic_id, id_interacted_with, id_post, opinion)
        VALUES
            (2, 1, 1, 2, 0, 0.10),
            (3, 1, 1, 3, 0, 0.12),
            (4, 1, 1, 4, 0, 0.05);
        """
    )
    connection.commit()

    class StubLLM:
        is_available = True

        def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
            if "target_left_young_1" in user_prompt:
                return "@target_left_young_1 climate action can help your community."
            if "target_left_young_2" in user_prompt:
                return "@target_left_young_2 climate action can help your community."
            return "@fallback climate action matters."

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    propaganda = PropagandaAgent(
        settings={
            "propaganda_campaigns": [
                {
                    "topic_id": 1,
                    "topic_name": "Climate",
                    "target_opinion": 0.8,
                    "target_opinion_group": "Supportive",
                    "target_agent_opinion_group": "Opposed",
                    "target_agent_opinion_group_bounds": {
                        "name": "Opposed",
                        "lower_bound": 0.0,
                        "upper_bound": 0.2,
                        "value": 0.1,
                    },
                    "target_leaning": "Left",
                    "target_age_classes": [
                        {"name": "Young", "age_start": 18, "age_end": 30}
                    ],
                }
            ],
            "epsilon": 0.05,
            "max_interaction_rounds": 4,
            "max_concurrent_targets": 2,
        },
        llm_client=StubLLM(),
    )
    propaganda.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Propaganda One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="propaganda",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=5),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = propaganda.on_tick(context, agent)

    assert [action.action_type for action in actions] == [
        "READ",
        "CREATE_POST",
        "CREATE_POST",
    ]
    payloads = [action.payload for action in actions[1:]]
    target_ids = {payload["propaganda_activity"]["target_uid"] for payload in payloads}
    assert target_ids == {2, 3}
    assert all("@target_right_old" not in payload["text"] for payload in payloads)
    assert all(payload["topic_ids"] == [1] for payload in payloads)

    executor = ActionExecutor(database)
    for action in actions[1:]:
        executor.execute(sa_connection, context=context, agent=agent, action=action)

    activity_count = sa_connection.execute(
        text("SELECT COUNT(*) FROM propaganda_activity")
    ).fetchone()[0]
    assert activity_count == 2
    inserted_topics = sa_connection.execute(
        text("SELECT post_id, topic_id FROM post_topics ORDER BY post_id, topic_id")
    ).fetchall()
    assert inserted_topics == [(1, 1), (2, 1)]
    sa_connection.close()
    connection.close()


def test_propaganda_does_not_target_other_adhoc_agents(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age, leaning)
        VALUES
            (2, 'comic_target', 'comic_target@example.org', 'secret', 'comic_relief', 'experiment', 'climate', 24, 'Left'),
            (3, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'climate', 24, 'Left');
        INSERT INTO agent_opinion (agent_id, tid, topic_id, id_interacted_with, id_post, opinion)
        VALUES
            (2, 1, 1, 2, 0, 0.10),
            (3, 1, 1, 3, 0, 0.12);
        """
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    propaganda = PropagandaAgent(
        settings={
            "propaganda_campaigns": [
                {
                    "topic_id": 1,
                    "topic_name": "Climate",
                    "target_opinion": 0.8,
                    "target_agent_opinion_group": "Opposed",
                    "target_agent_opinion_group_bounds": {
                        "name": "Opposed",
                        "lower_bound": 0.0,
                        "upper_bound": 0.2,
                        "value": 0.1,
                    },
                    "target_leaning": "Left",
                    "target_age_classes": [{"name": "Young", "age_start": 18, "age_end": 30}],
                }
            ]
        },
        llm_client=_FakeLLM(),
    )
    propaganda.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Propaganda One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="propaganda",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=10),
        managed_agents=(agent,),
        connection=sa_connection,
    )

    actions = propaganda.on_tick(context, agent)

    assert [action.action_type for action in actions] == ["READ", "CREATE_POST"]
    assert "@target_1" in actions[1].payload["text"]
    assert "@comic_target" not in actions[1].payload["text"]
    sa_connection.close()
    connection.close()


def test_personalized_message_is_sanitized_before_persisting(tmp_path: Path) -> None:
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
            return (
                "**To target_1@example.org**\n\n"
                "Please be aware that your comment was reviewed in the last **24-round moderation duration**, "
                "but it failed to meet our standards.\n\n"
                "Do not use abusive language again.\n\n"
                "Sincerely,\n"
                "Moderator"
            )

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

    assert actions[1].payload["system_message_text"] == "Do not use abusive language again."
    sa_connection.close()
    connection.close()


def test_moderator_uses_highest_available_post_toxicity_dimension(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        DROP TABLE post_toxicity;
        CREATE TABLE post_toxicity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            toxicity REAL DEFAULT 0 NOT NULL,
            severe_toxicity REAL DEFAULT 0,
            identity_attack REAL DEFAULT 0,
            insult REAL DEFAULT 0,
            profanity REAL DEFAULT 0,
            threat REAL DEFAULT 0,
            sexually_explicit REAL DEFAULT 0,
            flirtation REAL DEFAULT 0
        );
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age)
        VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'sports', 30);
        INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (1, 'this is abuse', 2, 1, 0);
        INSERT INTO post_toxicity (post_id, toxicity, insult) VALUES (1, 0.2, 0.91);
        """
    )
    connection.commit()
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    moderator = ModeratorAgent(
        settings={
            "toxicity_threshold": 0.5,
            "moderation_time_span": 3,
            "moderation_action_type": "one-fits-all",
            "candidate_window_rounds": 2,
        }
    )
    moderator.setup_database(database, sa_connection)
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
    assert actions[1].payload["post_id"] == 1
    sa_connection.close()
    connection.close()


def test_moderator_respects_daily_budget_within_same_day(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner)
        VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment');
        INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (1, 'this is abuse', 2, 1, 0);
        INSERT INTO post_toxicity (post_id, toxicity) VALUES (1, 0.9);
        """
    )
    connection.commit()
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    moderator = ModeratorAgent(
        settings={
            "toxicity_threshold": 0.5,
            "moderation_time_span": 3,
            "moderation_action_type": "one-fits-all",
            "candidate_window_rounds": 2,
        }
    )
    moderator.setup_database(database, sa_connection)
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=5),
        managed_agents=(),
        connection=sa_connection,
    )
    agent = AgentSpec(
        name="Moderator One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="moderator",
        activity_profile="Always On",
        daily_budget=1,
    )

    first_actions = moderator.on_tick(context, agent)
    assert [action.action_type for action in first_actions] == ["READ", "APPLY_MODERATION"]

    ActionExecutor(database).execute(
        sa_connection,
        context=context,
        agent=agent,
        action=first_actions[1],
    )

    second_actions = moderator.on_tick(context, agent)
    assert [action.action_type for action in second_actions] == ["READ"]
    assert database.count_moderations_for_agent_day(
        sa_connection,
        moderator_username="hello_1",
        day=0,
    ) == 1
    sa_connection.close()
    connection.close()


def test_moderator_daily_budget_resets_on_new_day(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO rounds (id, day, hour) VALUES (2, 1, 0);
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner)
        VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment');
        INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (1, 'this is abuse', 2, 1, 0);
        INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (2, 'still abusive today', 2, 2, 0);
        INSERT INTO post_toxicity (post_id, toxicity) VALUES (1, 0.9);
        INSERT INTO post_toxicity (post_id, toxicity) VALUES (2, 0.92);
        """
    )
    connection.commit()
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    moderator = ModeratorAgent(
        settings={
            "toxicity_threshold": 0.5,
            "moderation_time_span": 3,
            "moderation_action_type": "one-fits-all",
            "candidate_window_rounds": 5,
        }
    )
    moderator.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Moderator One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="moderator",
        activity_profile="Always On",
        daily_budget=1,
    )

    day_zero_context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=5),
        managed_agents=(),
        connection=sa_connection,
    )
    first_actions = moderator.on_tick(day_zero_context, agent)
    ActionExecutor(database).execute(
        sa_connection,
        context=day_zero_context,
        agent=agent,
        action=first_actions[1],
    )

    day_one_context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=2, day=1, slot=0),
        previous_round=day_zero_context.current_round,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=2, limit=5),
        managed_agents=(),
        connection=sa_connection,
    )
    second_day_actions = moderator.on_tick(day_one_context, agent)

    assert [action.action_type for action in second_day_actions] == ["READ", "APPLY_MODERATION"]
    assert second_day_actions[1].payload["post_id"] == 2
    assert database.count_moderations_for_agent_day(
        sa_connection,
        moderator_username="hello_1",
        day=0,
    ) == 1
    assert database.count_moderations_for_agent_day(
        sa_connection,
        moderator_username="hello_1",
        day=1,
    ) == 0
    sa_connection.close()
    connection.close()


def test_moderator_creates_shadow_ban_table_and_applies_ban_at_threshold(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner)
        VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment');
        INSERT INTO rounds (id, day, hour) VALUES (2, 0, 1);
        INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (1, 'first abusive post', 2, 1, 1);
        INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (2, 'second abusive post', 2, 2, 0);
        INSERT INTO post_toxicity (post_id, toxicity) VALUES (1, 0.91);
        INSERT INTO post_toxicity (post_id, toxicity) VALUES (2, 0.93);
        """
    )
    connection.commit()
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    moderator = ModeratorAgent(
        settings={
            "toxicity_threshold": 0.5,
            "moderation_time_span": 3,
            "moderation_action_type": "one-fits-all",
            "candidate_window_rounds": 5,
            "shadow_ban_enabled": "enabled",
            "shadow_ban_infraction_window_rounds": 24,
            "shadow_ban_n_infraction": 2,
            "shadow_ban_duration_rounds": 5,
        }
    )
    moderator.setup_database(database, sa_connection)
    assert database.has_table(sa_connection, "shadow_ban")

    agent = AgentSpec(
        name="Moderator One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="moderator",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=2, day=0, slot=1),
        previous_round=SimulationRound(id=1, day=0, slot=0),
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=2, limit=5),
        managed_agents=(),
        connection=sa_connection,
    )

    database.insert_moderation_event(
        sa_connection,
        moderator_username="hello_1",
        moderated_post_id=1,
        moderation_type="one-fits-all",
        round_id=1,
    )

    actions = moderator.on_tick(context, agent)
    moderation_action = actions[1]
    assert moderation_action.payload["infraction_count"] == 2
    assert moderation_action.payload["shadow_ban_applied"] is True
    assert "temporary shadow ban for 5 rounds" in moderation_action.payload["system_message_text"]

    ActionExecutor(database).execute(
        sa_connection,
        context=context,
        agent=agent,
        action=moderation_action,
    )

    bans = sa_connection.execute(
        database.table("shadow_ban").select().where(database.table("shadow_ban").c.uid == 2)
    ).mappings().all()
    assert len(bans) == 1
    assert bans[0]["start_tid"] == 2
    assert bans[0]["duration"] == 5
    sa_connection.close()
    connection.close()


def test_moderator_mentions_infraction_risk_before_shadow_ban_threshold(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner)
        VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment');
        INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (1, 'abusive post', 2, 1, 0);
        INSERT INTO post_toxicity (post_id, toxicity) VALUES (1, 0.88);
        """
    )
    connection.commit()
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    moderator = ModeratorAgent(
        settings={
            "toxicity_threshold": 0.5,
            "moderation_time_span": 3,
            "moderation_action_type": "one-fits-all",
            "candidate_window_rounds": 5,
            "shadow_ban_enabled": "enabled",
            "shadow_ban_infraction_window_rounds": 24,
            "shadow_ban_n_infraction": 3,
            "shadow_ban_duration_rounds": 6,
        }
    )
    moderator.setup_database(database, sa_connection)
    agent = AgentSpec(
        name="Moderator One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="moderator",
        activity_profile="Always On",
        daily_budget=24,
    )
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=1, day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=5),
        managed_agents=(),
        connection=sa_connection,
    )

    actions = moderator.on_tick(context, agent)
    moderation_action = actions[1]
    assert moderation_action.payload["shadow_ban_applied"] is False
    assert moderation_action.payload["infraction_count"] == 1
    assert "reach 3 infractions" in moderation_action.payload["system_message_text"]
    assert "2 infractions remain" in moderation_action.payload["system_message_text"]
    sa_connection.close()
    connection.close()


def test_moderator_creates_banned_table_only_when_ban_enabled(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    _build_db(db_path).close()
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()

    moderator_disabled = ModeratorAgent(
        settings={
            "toxicity_threshold": 0.5,
            "moderation_time_span": 3,
            "moderation_action_type": "one-fits-all",
        }
    )
    moderator_disabled.setup_database(database, sa_connection)
    assert database.has_table(sa_connection, "banned") is False

    moderator_enabled = ModeratorAgent(
        settings={
            "toxicity_threshold": 0.5,
            "moderation_time_span": 3,
            "moderation_action_type": "one-fits-all",
            "ban_enabled": "enabled",
            "ban_infraction_window_rounds": 24,
            "ban_n_infraction": 2,
        }
    )
    moderator_enabled.setup_database(database, sa_connection)
    assert database.has_table(sa_connection, "banned") is True
    sa_connection.close()


def test_moderator_warns_at_ban_threshold_before_applying_ban(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner)
        VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment');
        INSERT INTO rounds (id, day, hour) VALUES (2, 0, 1);
        INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (1, 'old abuse', 2, 1, 1);
        INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (2, 'new abuse', 2, 2, 0);
        INSERT INTO post_toxicity (post_id, toxicity) VALUES (1, 0.91);
        INSERT INTO post_toxicity (post_id, toxicity) VALUES (2, 0.95);
        """
    )
    connection.commit()
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    moderator = ModeratorAgent(
        settings={
            "toxicity_threshold": 0.5,
            "moderation_time_span": 3,
            "moderation_action_type": "one-fits-all",
            "candidate_window_rounds": 5,
            "ban_enabled": "enabled",
            "ban_infraction_window_rounds": 24,
            "ban_n_infraction": 2,
        }
    )
    moderator.setup_database(database, sa_connection)
    database.insert_moderation_event(
        sa_connection,
        moderator_username="hello_1",
        moderated_post_id=1,
        moderation_type="one-fits-all",
        round_id=1,
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
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=2, day=0, slot=1),
        previous_round=SimulationRound(id=1, day=0, slot=0),
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=2, limit=5),
        managed_agents=(),
        connection=sa_connection,
    )

    actions = moderator.on_tick(context, agent)
    moderation_action = actions[1]
    assert moderation_action.payload["ban_warning"] is True
    assert moderation_action.payload["ban_applied"] is False
    assert "next infraction within the configured window will result in a permanent ban" in moderation_action.payload["system_message_text"]

    ActionExecutor(database).execute(
        sa_connection,
        context=context,
        agent=agent,
        action=moderation_action,
    )
    left_on = sa_connection.execute(
        text("SELECT left_on FROM user_mgmt WHERE id = 2")
    ).first()
    banned_rows = sa_connection.execute(text("SELECT uid, tid FROM banned")).fetchall()
    assert left_on == (None,)
    assert banned_rows == []
    sa_connection.close()
    connection.close()


def test_moderator_permanently_bans_user_after_threshold_plus_one(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner)
        VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment');
        INSERT INTO rounds (id, day, hour) VALUES (2, 0, 1);
        INSERT INTO rounds (id, day, hour) VALUES (3, 0, 2);
        INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (1, 'old abuse 1', 2, 1, 1);
        INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (2, 'old abuse 2', 2, 2, 1);
        INSERT INTO post (id, tweet, user_id, round, moderated) VALUES (3, 'ban me', 2, 3, 0);
        INSERT INTO post_toxicity (post_id, toxicity) VALUES (1, 0.91);
        INSERT INTO post_toxicity (post_id, toxicity) VALUES (2, 0.92);
        INSERT INTO post_toxicity (post_id, toxicity) VALUES (3, 0.99);
        """
    )
    connection.commit()
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    moderator = ModeratorAgent(
        settings={
            "toxicity_threshold": 0.5,
            "moderation_time_span": 3,
            "moderation_action_type": "one-fits-all",
            "candidate_window_rounds": 5,
            "ban_enabled": "enabled",
            "ban_infraction_window_rounds": 24,
            "ban_n_infraction": 2,
        }
    )
    moderator.setup_database(database, sa_connection)
    database.insert_moderation_event(
        sa_connection,
        moderator_username="hello_1",
        moderated_post_id=1,
        moderation_type="one-fits-all",
        round_id=1,
    )
    database.insert_moderation_event(
        sa_connection,
        moderator_username="hello_1",
        moderated_post_id=2,
        moderation_type="one-fits-all",
        round_id=2,
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
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=3, day=0, slot=2),
        previous_round=SimulationRound(id=2, day=0, slot=1),
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=3, limit=5),
        managed_agents=(),
        connection=sa_connection,
    )

    actions = moderator.on_tick(context, agent)
    moderation_action = actions[1]
    assert moderation_action.payload["ban_applied"] is True
    assert "now permanently banned from the platform" in moderation_action.payload["system_message_text"]

    ActionExecutor(database).execute(
        sa_connection,
        context=context,
        agent=agent,
        action=moderation_action,
    )

    left_on = sa_connection.execute(
        text("SELECT left_on FROM user_mgmt WHERE id = 2")
    ).first()
    banned_rows = sa_connection.execute(text("SELECT uid, tid FROM banned")).fetchall()
    assert left_on == (3,)
    assert banned_rows == [(2, 3)]
    assert database.user_is_banned(sa_connection, user_id=2) is True
    sa_connection.close()
    connection.close()


class _FakeLLM:
    is_available = True

    def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
        if "Target username:" in user_prompt:
            target = user_prompt.split("Target username:", 1)[1].splitlines()[0].strip()
            return f"@{target} I think this topic deserves a closer look."
        if "Target user:" in user_prompt:
            target = user_prompt.split("Target user:", 1)[1].splitlines()[0].strip()
            if target and target.lower() != "none":
                return f"@{target} Climate deserves more attention."
        return "Climate deserves more attention."


def test_executor_supports_mop_puppet_actions(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment')"
    )
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner) VALUES (3, 'hello_1_puppet_1', 'puppet@example.org', 'secret', 'mop_puppet', 'hello_1')"
    )
    connection.execute(
        "INSERT INTO daily_schedules (id, p_id, timestamp, action_type, payload, scheduled_time, schedule_day, status) VALUES (1, 3, 1, 'post', '{}', 1, 0, 'dispatched')"
    )
    connection.commit()
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
        name="MoP One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="master_of_puppets",
        activity_profile="Always On",
        daily_budget=24,
    )

    executor.execute(
        sa_connection,
        context=context,
        agent=agent,
        action=AgentAction(
            agent_type="master_of_puppets",
            action_type="CREATE_POST",
            payload={
                "acting_username": "hello_1_puppet_1",
                "text": "@target_1 Climate matters.",
                "topic_ids": [1],
                "mop_activity": {
                    "schedule_id": 1,
                    "action_type": "post",
                    "details": {"campaign_topic_id": 1},
                },
            },
        ),
    )
    executor.execute(
        sa_connection,
        context=context,
        agent=agent,
        action=AgentAction(
            agent_type="master_of_puppets",
            action_type="FOLLOW_USER",
            payload={
                "acting_username": "hello_1_puppet_1",
                "target_user_id": 2,
                "mop_activity": {"action_type": "expand", "details": {"target_user_id": 2}},
            },
        ),
    )
    executor.execute(
        sa_connection,
        context=context,
        agent=agent,
        action=AgentAction(
            agent_type="master_of_puppets",
            action_type="REACT_POST",
            payload={
                "acting_username": "hello_1_puppet_1",
                "post_id": 1,
                "reaction_type": "like",
                "mop_activity": {
                    "action_type": "boost",
                    "target_post_id": 1,
                    "details": {"boost_mode": "like"},
                },
            },
        ),
    )
    executor.execute(
        sa_connection,
        context=context,
        agent=agent,
        action=AgentAction(
            agent_type="master_of_puppets",
            action_type="SHARE_POST",
            payload={
                "acting_username": "hello_1_puppet_1",
                "post_id": 1,
                "text": "Climate matters.",
                "topic_ids": [1],
                "mop_activity": {
                    "action_type": "boost",
                    "target_post_id": 1,
                    "details": {"boost_mode": "share"},
                },
            },
        ),
    )

    assert sa_connection.execute(
        text("select count(*) from post where user_id = 3")
    ).scalar_one() == 2
    assert sa_connection.execute(
        text("select count(*) from follow where user_id = 3 and follower_id = 2 and action = 'follow'")
    ).scalar_one() == 1
    assert sa_connection.execute(
        text("select count(*) from reactions where user_id = 3 and post_id = 1 and type = 'like'")
    ).scalar_one() == 1
    assert sa_connection.execute(
        text("select status, executed_round_id from daily_schedules where id = 1")
    ).fetchone() == ("executed", 1)
    assert sa_connection.execute(
        text("select count(*) from activity_logs where p_id = 3 and status = 'executed'")
    ).scalar_one() == 4
    sa_connection.close()
    connection.close()


def test_mop_spawns_puppets_and_generates_due_actions(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age, leaning) VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'Climate', 30, 'Center')"
    )
    connection.commit()
    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    mop = MasterOfPuppetsAgent(
        settings={
            "puppet_count": 2,
            "post_budget_percentage": 50,
            "support_budget_percentage": 0,
            "network_budget_percentage": 50,
            "boost_lookback_hours": 12,
            "mop_campaigns": [
                {
                    "topic_id": 1,
                    "topic_name": "Climate",
                    "target_opinion": 0.8,
                    "target_opinion_group": "Supportive",
                }
            ],
        },
        llm_client=_FakeLLM(),
    )
    mop.setup_database(database, sa_connection)
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=24, day=0, slot=23),
        previous_round=SimulationRound(id=23, day=0, slot=22),
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=20),
        managed_agents=(),
        connection=sa_connection,
    )
    agent = AgentSpec(
        name="MoP One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="master_of_puppets",
        activity_profile="Always On",
        daily_budget=24,
    )

    actions = mop.on_tick(context, agent)

    assert sa_connection.execute(
        text("select count(*) from puppet_registry where parent_mop_id = 1 and is_banned = 0")
    ).scalar_one() == 2
    puppet_usernames = [
        row[0]
        for row in sa_connection.execute(
            text("select username from puppet_registry where parent_mop_id = 1 order by username asc")
        ).fetchall()
    ]
    assert all("_puppet_" not in username for username in puppet_usernames)
    assert all("_" in username for username in puppet_usernames)
    assert sa_connection.execute(
        text("select count(*) from daily_schedules")
    ).scalar_one() >= 2
    assert sa_connection.execute(
        text("select count(*) from agent_opinion where topic_id = 1 and agent_id in (select p_id from puppet_registry)")
    ).scalar_one() == 2
    assert any(action.action_type == "CREATE_POST" for action in actions)
    assert any(action.action_type == "FOLLOW_USER" for action in actions)
    sa_connection.close()
    connection.close()


def test_mop_strips_echoed_puppet_metadata_from_llm_output(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age, leaning) VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'Climate', 30, 'Center')"
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()

    class StubLLM:
        is_available = True

        def invoke_text(self, *, system_prompt: str, user_prompt: str) -> str:
            return (
                '"@target_1 Publications are the ultimate test of intellectual courage! '
                'Sharing your ideas with the world takes guts. '
                '#PublishOrPerish #AcademicHonor #IntellectualFreedom" '
                "(Puppet ID: 446fb614-c1b8-420c-ba1d-ea151a74c925) — posted at 14:04:21"
            )

    mop = MasterOfPuppetsAgent(
        settings={
            "puppet_count": 1,
            "post_budget_percentage": 100,
            "support_budget_percentage": 0,
            "network_budget_percentage": 0,
            "mop_campaigns": [
                {
                    "topic_id": 1,
                    "topic_name": "Climate",
                    "target_opinion": 0.8,
                    "target_opinion_group": "Supportive",
                }
            ],
        },
        llm_client=StubLLM(),
    )
    mop.setup_database(database, sa_connection)
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id=24, day=0, slot=23),
        previous_round=SimulationRound(id=23, day=0, slot=22),
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=1, limit=20),
        managed_agents=(),
        connection=sa_connection,
    )
    agent = AgentSpec(
        name="MoP One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="master_of_puppets",
        activity_profile="Always On",
        daily_budget=24,
    )

    actions = mop.on_tick(context, agent)
    create_post = next(action for action in actions if action.action_type == "CREATE_POST")

    assert "Puppet ID" not in create_post.payload["text"]
    assert "posted at" not in create_post.payload["text"]
    assert create_post.payload["text"].startswith("@target_1 ")
    sa_connection.close()
    connection.close()


def test_mop_minimal_experiment_executes_post_expand_and_boost(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    connection = _build_db(db_path)
    connection.executescript(
        """
        INSERT INTO rounds (id, day, hour) VALUES (24, 0, 23);
        INSERT INTO rounds (id, day, hour) VALUES (48, 1, 23);
        INSERT INTO rounds (id, day, hour) VALUES (72, 2, 23);
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner, interests, age, leaning)
        VALUES
            (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 'Climate', 30, 'Center'),
            (3, 'target_2', 'target_2@example.org', 'secret', 'human', 'experiment', 'Climate', 41, 'Center-Left'),
            (4, 'target_3', 'target_3@example.org', 'secret', 'human', 'experiment', 'Climate', 27, 'Center-Right');
        """
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    executor = ActionExecutor(database)
    agent = AgentSpec(
        name="MoP One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="master_of_puppets",
        activity_profile="Always On",
        daily_budget=2,
    )

    post_mop = MasterOfPuppetsAgent(
        settings={
            "puppet_count": 2,
            "post_budget_percentage": 100,
            "support_budget_percentage": 0,
            "network_budget_percentage": 0,
            "boost_lookback_hours": 72,
            "mop_campaigns": [
                {
                    "topic_id": 1,
                    "topic_name": "Climate",
                    "target_opinion": 0.8,
                    "target_opinion_group": "Supportive",
                }
            ],
        },
        llm_client=_FakeLLM(),
    )
    post_mop.setup_database(database, sa_connection)
    day0_context = AgentContext(
        client_id="mop-client",
        current_round=SimulationRound(id=24, day=0, slot=23),
        previous_round=SimulationRound(id=23, day=0, slot=22),
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=24, limit=20),
        managed_agents=(),
        connection=sa_connection,
    )

    day0_actions = [
        action
        for action in post_mop.on_tick(day0_context, agent)
        if action.action_type != "READ"
    ]
    assert [action.action_type for action in day0_actions] == ["CREATE_POST", "CREATE_POST"]
    for action in day0_actions:
        executor.execute(sa_connection, context=day0_context, agent=agent, action=action)

    assert sa_connection.execute(
        text("select count(*) from post where user_id in (select p_id from puppet_registry)")
    ).scalar_one() == 2
    assert sa_connection.execute(
        text("select count(*) from post_topics where post_id in (select id from post where user_id in (select p_id from puppet_registry))")
    ).scalar_one() == 2
    assert sa_connection.execute(
        text("select count(*) from activity_logs where action_type = 'post' and status = 'executed'")
    ).scalar_one() == 2

    expand_mop = MasterOfPuppetsAgent(
        settings={
            "puppet_count": 2,
            "post_budget_percentage": 0,
            "support_budget_percentage": 0,
            "network_budget_percentage": 100,
            "boost_lookback_hours": 72,
            "mop_campaigns": [
                {
                    "topic_id": 1,
                    "topic_name": "Climate",
                    "target_opinion": 0.8,
                    "target_opinion_group": "Supportive",
                }
            ],
        },
        llm_client=_FakeLLM(),
    )
    expand_mop.setup_database(database, sa_connection)
    day1_context = AgentContext(
        client_id="mop-client",
        current_round=SimulationRound(id=48, day=1, slot=23),
        previous_round=SimulationRound(id=47, day=1, slot=22),
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=48, limit=20),
        managed_agents=(),
        connection=sa_connection,
    )

    day1_actions = [
        action
        for action in expand_mop.on_tick(day1_context, agent)
        if action.action_type != "READ"
    ]
    assert [action.action_type for action in day1_actions] == ["FOLLOW_USER", "FOLLOW_USER"]
    for action in day1_actions:
        executor.execute(sa_connection, context=day1_context, agent=agent, action=action)

    assert sa_connection.execute(text("select count(*) from follow")).scalar_one() == 2
    assert sa_connection.execute(
        text("select count(*) from activity_logs where action_type = 'expand' and status = 'executed'")
    ).scalar_one() == 2

    boost_mop = MasterOfPuppetsAgent(
        settings={
            "puppet_count": 2,
            "post_budget_percentage": 0,
            "support_budget_percentage": 100,
            "network_budget_percentage": 0,
            "boost_lookback_hours": 72,
            "mop_campaigns": [
                {
                    "topic_id": 1,
                    "topic_name": "Climate",
                    "target_opinion": 0.8,
                    "target_opinion_group": "Supportive",
                }
            ],
        },
        llm_client=_FakeLLM(),
    )
    boost_mop.setup_database(database, sa_connection)
    day2_context = AgentContext(
        client_id="mop-client",
        current_round=SimulationRound(id=72, day=2, slot=23),
        previous_round=SimulationRound(id=71, day=2, slot=22),
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id=72, limit=50),
        managed_agents=(),
        connection=sa_connection,
    )

    import unittest.mock

    with unittest.mock.patch(
        "y_agents_plugins.plugins.master_of_puppets.random.random", return_value=0.9
    ):
        day2_actions = [
            action
            for action in boost_mop.on_tick(day2_context, agent)
            if action.action_type != "READ"
        ]
    assert [action.action_type for action in day2_actions] == ["SHARE_POST", "SHARE_POST"]
    for action in day2_actions:
        executor.execute(sa_connection, context=day2_context, agent=agent, action=action)

    assert sa_connection.execute(
        text("select count(*) from post where shared_from != -1 and user_id in (select p_id from puppet_registry)")
    ).scalar_one() == 2
    assert sa_connection.execute(
        text("select count(*) from post_topics where post_id in (select id from post where shared_from != -1)")
    ).scalar_one() == 2
    assert sa_connection.execute(
        text("select count(*) from activity_logs where action_type = 'boost' and status = 'executed'")
    ).scalar_one() == 2
    assert sa_connection.execute(
        text("select count(*) from agent_opinion where topic_id = 1 and opinion = 0.8 and agent_id in (select p_id from puppet_registry)")
    ).scalar_one() == 2

    sa_connection.close()
    connection.close()


def test_mop_supports_uuid_topic_ids_on_hpc_schema(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation_uuid.db"
    connection = _build_uuid_hpc_db(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner, round_actions, is_page, activity_profile, daily_activity_level, last_active_day, interests, age, leaning) "
        "VALUES ('target-1', 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 8, 0, 'Always On', 1, 0, 'Climate', 30, 'Center')"
    )
    connection.commit()

    database = ExperimentDatabase(db_path)
    sa_connection = database.connect()
    mop = MasterOfPuppetsAgent(
        settings={
            "puppet_count": 1,
            "post_budget_percentage": 100,
            "support_budget_percentage": 0,
            "network_budget_percentage": 0,
            "boost_lookback_hours": 12,
            "mop_campaigns": [
                {
                    "topic_id": "topic-climate",
                    "topic_name": "Climate",
                    "target_opinion": 0.8,
                    "target_opinion_group": "Supportive",
                }
            ],
        },
        llm_client=_FakeLLM(),
    )
    mop.setup_database(database, sa_connection)
    context = AgentContext(
        client_id="client-1",
        current_round=SimulationRound(id="round-1", day=0, slot=0),
        previous_round=None,
        users=database.get_users(sa_connection),
        recent_posts=database.get_recent_posts(sa_connection, round_id="round-1", limit=20),
        managed_agents=(),
        connection=sa_connection,
    )
    agent = AgentSpec(
        name="MoP One",
        username="hello_1",
        email="hello_1@example.org",
        password="secret",
        agent_type="master_of_puppets",
        activity_profile="Always On",
        daily_budget=4,
    )

    actions = mop.on_tick(context, agent)

    assert any(action.action_type == "CREATE_POST" for action in actions)
    assert sa_connection.execute(
        text("select count(*) from puppet_registry")
    ).scalar_one() == 1
    assert sa_connection.execute(
        text(
            "select count(*) from agent_opinion "
            "where topic_id = 'topic-climate' and agent_id in (select p_id from puppet_registry)"
        )
    ).scalar_one() == 1
    sa_connection.close()
    connection.close()
