from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import text

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
            age INTEGER,
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
    moderation_comment = sa_connection.execute(
        database.table("post").select().where(database.table("post").c.id != 1)
    ).mappings().first()
    assert moderation_comment["tweet"] == "Adjust your behavior."
    assert moderation_comment["comment_to"] == 1
    assert moderation_comment["is_moderation_comment"] == 1
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
