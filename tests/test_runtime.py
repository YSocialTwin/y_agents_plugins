from __future__ import annotations

import sqlite3
import json
from pathlib import Path

import pytest

from y_agents_plugins.config import (
    AppConfig,
    ClientConfig,
    DatabaseConfig,
    LLMServerConfig,
    SimulationConfig,
)
from y_agents_plugins.runtime import ClientApp
from y_agents_plugins.runtime.app import build_default_registry
from y_agents_plugins.runtime import manifest as manifest_module


def _llm_servers():
    return {
        "llm": "http://127.0.0.1:11434/v1",
        "llm_api_key": "NULL",
        "llm_max_tokens": -1,
        "llm_temperature": 1.5,
        "llm_v": "http://127.0.0.1:11434/v1",
        "llm_v_api_key": "NULL",
        "llm_v_max_tokens": 300,
        "llm_v_temperature": 0.5,
        "api": "http://127.0.0.1:5001/",
    }


def _simulation(tmp_path: Path, agents_path: Path):
    return {
        "days": 30,
        "slots": 24,
        "population_json_path": str(agents_path),
        "name": "test",
        "activity_profiles": {
            "Always On": ",".join(str(slot) for slot in range(24)),
            "Work Hours": "9,10,11,12,13,14,15,16,17",
        },
    }


def _moderator_settings(**overrides):
    settings = {
        "toxicity_threshold": 0.6,
        "moderation_time_span": 4,
        "moderation_action_type": "one-fits-all",
        "candidate_window_rounds": 3,
    }
    settings.update(overrides)
    return settings


def _build_db(path: Path) -> None:
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
            leaning TEXT,
            interests TEXT,
            age INTEGER,
            oe TEXT,
            co TEXT,
            ex TEXT,
            ag TEXT,
            ne TEXT,
            recsys_type TEXT,
            language TEXT,
            owner TEXT,
            education_level TEXT,
            joined_on INTEGER,
            frecsys_type TEXT
        );
        CREATE TABLE post (
            id INTEGER PRIMARY KEY,
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
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner, joined_on)
        VALUES (1, 'alice', 'alice@example.org', 'secret', 'human', 'experiment', 1);
        INSERT INTO post (id, tweet, user_id, round) VALUES (1, 'hello world', 1, 1);
        """
    )
    connection.commit()
    connection.close()


def _build_agents_json(
    path: Path,
    *,
    agent_type: str = "moderator",
    parameters: dict | None = None,
) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "name": "Moderator One",
                    "username": "mod_1",
                    "email": "mod_1@example.org",
                    "password": "secret",
                    "agent_type": agent_type,
                    "activity_profile": "Always On",
                    "daily_budget": 42,
                    "parameters": parameters or {"toxicity_keywords": ["abuse"]},
                }
            ]
        )
    )


def test_client_app_binds_exactly_one_agent_type(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    agents_path = tmp_path / "agents.json"
    _build_db(db_path)
    _build_agents_json(agents_path)
    config = AppConfig(
        database=DatabaseConfig(sqlite_path=db_path, poll_interval_seconds=0.0),
        client=ClientConfig(
            client_id="moderator-client",
            agent_type="moderator",
            agents_json_path=agents_path,
            llm_servers=LLMServerConfig(values=_llm_servers()),
            simulation=SimulationConfig(
                days=30,
                slots=24,
                population_json_path=agents_path,
                raw=_simulation(tmp_path, agents_path),
            ),
            agent_settings=_moderator_settings(),
            max_ticks=1,
        ),
    )

    app = ClientApp(config)

    assert app.agent.agent_type == "moderator"
    assert app.config.client.agent_type == "moderator"


def test_unknown_agent_type_is_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    agents_path = tmp_path / "agents.json"
    _build_db(db_path)
    _build_agents_json(agents_path, agent_type="unknown")
    config = AppConfig(
        database=DatabaseConfig(sqlite_path=db_path),
        client=ClientConfig(
            client_id="broken-client",
            agent_type="unknown",
            agents_json_path=agents_path,
            llm_servers=LLMServerConfig(values=_llm_servers()),
            simulation=SimulationConfig(
                days=30,
                slots=24,
                population_json_path=agents_path,
                raw=_simulation(tmp_path, agents_path),
            ),
        ),
    )

    with pytest.raises(ValueError, match="Unknown agent_type"):
        ClientApp(config)


def test_client_registers_agents_in_user_mgmt(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    agents_path = tmp_path / "agents.json"
    _build_db(db_path)
    _build_agents_json(agents_path)
    config = AppConfig(
        database=DatabaseConfig(sqlite_path=db_path, poll_interval_seconds=0.0),
        client=ClientConfig(
            client_id="moderator-client",
            agent_type="moderator",
            agents_json_path=agents_path,
            llm_servers=LLMServerConfig(values=_llm_servers()),
            simulation=SimulationConfig(
                days=30,
                slots=24,
                population_json_path=agents_path,
                raw=_simulation(tmp_path, agents_path),
            ),
            agent_settings=_moderator_settings(),
            max_ticks=1,
        ),
    )

    app = ClientApp(config)
    app.run()

    connection = sqlite3.connect(db_path)
    row = connection.execute(
        "SELECT username, email, user_type FROM user_mgmt WHERE username = 'mod_1'"
    ).fetchone()
    connection.close()

    assert row == ("mod_1", "mod_1@example.org", "moderator")


def test_agents_json_defaults_to_simulation_population_path(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    agents_path = tmp_path / "agents.json"
    _build_db(db_path)
    _build_agents_json(agents_path)

    config = AppConfig(
        database=DatabaseConfig(sqlite_path=db_path, poll_interval_seconds=0.0),
        client=ClientConfig(
            client_id="moderator-client",
            agent_type="moderator",
            llm_servers=LLMServerConfig(values=_llm_servers()),
            simulation=SimulationConfig(
                days=30,
                slots=24,
                population_json_path=agents_path,
                raw=_simulation(tmp_path, agents_path),
            ),
            max_ticks=1,
        ),
    )

    assert config.client.agents_json_path == agents_path


def test_default_registry_includes_propaganda_agent() -> None:
    registry = build_default_registry()

    assert "propaganda" in registry.supported_types


def test_default_registry_includes_master_of_puppets_agent() -> None:
    registry = build_default_registry()

    assert "master_of_puppets" in registry.supported_types


def test_missing_agent_required_fields_are_rejected(tmp_path: Path) -> None:
    agents_path = tmp_path / "agents.json"
    agents_path.write_text(
        json.dumps([{"name": "Broken", "username": "broken", "email": "b@example.org", "agent_type": "moderator"}])
    )
    db_path = tmp_path / "simulation.db"
    _build_db(db_path)

    with pytest.raises(ValueError, match="activity_profile"):
        ClientApp(
            AppConfig(
                database=DatabaseConfig(sqlite_path=db_path),
                client=ClientConfig(
                    client_id="moderator-client",
                    agent_type="moderator",
                    agents_json_path=agents_path,
                    llm_servers=LLMServerConfig(values=_llm_servers()),
                    simulation=SimulationConfig(
                        days=30,
                        slots=24,
                        population_json_path=agents_path,
                        raw=_simulation(tmp_path, agents_path),
                    ),
                ),
            )
        )


def test_client_app_accepts_moderator_settings_from_agent_parameters(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "simulation.db"
    agents_path = tmp_path / "agents.json"
    _build_db(db_path)
    _build_agents_json(
        agents_path,
        parameters={
            "toxicity_threshold": "0.6",
            "moderation_time_span": "4",
            "moderation_action_type": "one-fits-all",
            "candidate_window_rounds": "3",
        },
    )
    config = AppConfig(
        database=DatabaseConfig(sqlite_path=db_path, poll_interval_seconds=0.0),
        client=ClientConfig(
            client_id="moderator-client",
            agent_type="moderator",
            agents_json_path=agents_path,
            llm_servers=LLMServerConfig(values=_llm_servers()),
            simulation=SimulationConfig(
                days=30,
                slots=24,
                population_json_path=agents_path,
                raw=_simulation(tmp_path, agents_path),
            ),
            agent_settings={},
            max_ticks=1,
        ),
    )

    app = ClientApp(config)
    app.run()

    connection = sqlite3.connect(db_path)
    row = connection.execute(
        "SELECT strategy_key FROM plugin_moderation_strategies ORDER BY strategy_key"
    ).fetchall()
    connection.close()

    assert row == [
        ("one-fits-all",),
        ("personalized",),
    ]


def test_second_moderator_client_reuses_existing_plugin_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    agents_a = tmp_path / "agents_a.json"
    agents_b = tmp_path / "agents_b.json"
    _build_db(db_path)
    moderator_parameters = {
        "toxicity_threshold": "0.6",
        "moderation_time_span": "4",
        "moderation_action_type": "one-fits-all",
        "candidate_window_rounds": "3",
    }
    _build_agents_json(agents_a, parameters=moderator_parameters)
    _build_agents_json(agents_b, parameters=moderator_parameters)

    def _config(client_id: str, agents_path: Path) -> AppConfig:
        return AppConfig(
            database=DatabaseConfig(sqlite_path=db_path, poll_interval_seconds=0.0),
            client=ClientConfig(
                client_id=client_id,
                agent_type="moderator",
                agents_json_path=agents_path,
                llm_servers=LLMServerConfig(values=_llm_servers()),
                simulation=SimulationConfig(
                    days=30,
                    slots=24,
                    population_json_path=agents_path,
                    raw=_simulation(tmp_path, agents_path),
                ),
                agent_settings={},
                max_ticks=1,
            ),
        )

    ClientApp(_config("moderator-a", agents_a)).run()
    ClientApp(_config("moderator-b", agents_b)).run()

    connection = sqlite3.connect(db_path)
    counts = connection.execute(
        "SELECT COUNT(*) FROM plugin_moderation_strategies"
    ).fetchone()[0]
    connection.close()

    assert counts == 2


def test_manifest_loader_prefers_meta_registry(tmp_path: Path, monkeypatch) -> None:
    plugin_root = tmp_path / "plugin"
    runtime_dir = plugin_root / "src" / "y_agents_plugins" / "runtime"
    runtime_dir.mkdir(parents=True)
    registry_path = plugin_root / "meta" / "registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(
        json.dumps(
            {
                "agent_types": [
                    {
                        "agent_type": "moderator",
                        "display_name": "Moderator Agent",
                        "description": "desc",
                        "parameters": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        manifest_module,
        "__file__",
        str(runtime_dir / "manifest.py"),
        raising=False,
    )

    manifest = manifest_module.load_agent_type_manifest()

    assert manifest.require_known_agent_type("moderator").display_name == "Moderator Agent"


def test_missing_client_llm_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="LLM/server fields"):
        LLMServerConfig(values={"llm": "http://127.0.0.1:11434/v1"})


def test_unknown_agent_activity_profile_is_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    agents_path = tmp_path / "agents.json"
    _build_db(db_path)
    agents_path.write_text(
        json.dumps(
            [
                {
                    "name": "Moderator One",
                    "username": "mod_1",
                    "email": "mod_1@example.org",
                    "password": "secret",
                    "agent_type": "moderator",
                    "activity_profile": "Night Shift",
                    "daily_budget": 42,
                }
            ]
        )
    )
    config = AppConfig(
        database=DatabaseConfig(sqlite_path=db_path),
        client=ClientConfig(
            client_id="moderator-client",
            agent_type="moderator",
            agents_json_path=agents_path,
            llm_servers=LLMServerConfig(values=_llm_servers()),
            simulation=SimulationConfig(
                days=30,
                slots=24,
                population_json_path=agents_path,
                raw=_simulation(tmp_path, agents_path),
            ),
        ),
    )

    with pytest.raises(ValueError, match="Unknown activity_profile"):
        ClientApp(config)


def test_client_supports_sqlalchemy_url(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    agents_path = tmp_path / "agents.json"
    _build_db(db_path)
    _build_agents_json(agents_path, agent_type="hello_world")
    config = AppConfig(
        database=DatabaseConfig(sqlalchemy_url=f"sqlite:///{db_path}", poll_interval_seconds=0.0),
        client=ClientConfig(
            client_id="hello-client",
            agent_type="hello_world",
            agents_json_path=agents_path,
            llm_servers=LLMServerConfig(values=_llm_servers()),
            simulation=SimulationConfig(
                days=30,
                slots=24,
                population_json_path=agents_path,
                raw=_simulation(tmp_path, agents_path),
            ),
            max_ticks=1,
        ),
    )

    app = ClientApp(config)

    assert app.database.database_url == f"sqlite:///{db_path}"


def test_client_exposes_langchain_llm_configuration(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    agents_path = tmp_path / "agents.json"
    _build_db(db_path)
    _build_agents_json(agents_path, agent_type="hello_world")
    config = AppConfig(
        database=DatabaseConfig(sqlite_path=db_path, poll_interval_seconds=0.0),
        client=ClientConfig(
            client_id="hello-client",
            agent_type="hello_world",
            agents_json_path=agents_path,
            llm_servers=LLMServerConfig(values=_llm_servers()),
            simulation=SimulationConfig(
                days=30,
                slots=24,
                population_json_path=agents_path,
                raw=_simulation(tmp_path, agents_path),
            ),
            agents_settings={"llm_agents": ["llama3.2"]},
            max_ticks=1,
        ),
    )

    app = ClientApp(config)

    assert app.llm.is_available is True
    assert app.llm.config.model == "llama3.2"


def test_moderator_client_bootstraps_plugin_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    agents_path = tmp_path / "agents.json"
    _build_db(db_path)
    connection = sqlite3.connect(db_path)
    connection.execute(
        "INSERT INTO user_mgmt (id, username, email, password, user_type, owner, joined_on) VALUES (2, 'target_1', 'target_1@example.org', 'secret', 'human', 'experiment', 1)"
    )
    connection.execute("UPDATE post SET tweet = 'this is abusive content' WHERE id = 1")
    connection.execute("UPDATE post SET user_id = 2 WHERE id = 1")
    connection.execute(
        "INSERT INTO reported (type, to_uid, to_post, from_uid, tid) VALUES ('post', 2, 1, 1, 1)"
    )
    connection.execute(
        "INSERT INTO post_toxicity (post_id, toxicity) VALUES (1, 0.8)"
    )
    connection.commit()
    connection.close()
    _build_agents_json(agents_path)
    config = AppConfig(
        database=DatabaseConfig(sqlite_path=db_path, poll_interval_seconds=0.0),
        client=ClientConfig(
            client_id="moderator-client",
            agent_type="moderator",
            agents_json_path=agents_path,
            llm_servers=LLMServerConfig(values=_llm_servers()),
            simulation=SimulationConfig(
                days=30,
                slots=24,
                population_json_path=agents_path,
                raw=_simulation(tmp_path, agents_path),
            ),
            agent_settings=_moderator_settings(),
            max_ticks=1,
        ),
    )

    ClientApp(config).run()

    connection = sqlite3.connect(db_path)
    strategies = connection.execute(
        "SELECT strategy_key FROM plugin_moderation_strategies ORDER BY strategy_key"
    ).fetchall()
    counts = connection.execute(
        "SELECT moderated_agent_id, moderation_count FROM plugin_moderation_counts"
    ).fetchall()
    actions = connection.execute(
        "SELECT moderated_post_id, moderation_type, round_id, generated_comment_id FROM plugin_moderation_actions"
    ).fetchall()
    sys_messages = connection.execute(
        "SELECT type, to_uid, message, from_round, duration FROM sys_messages"
    ).fetchall()
    moderated = connection.execute("SELECT moderated FROM post WHERE id = 1").fetchone()
    moderation_comment = connection.execute(
        "SELECT tweet, user_id, comment_to, thread_id, round FROM post WHERE id = 2"
    ).fetchone()
    connection.close()

    assert strategies == [("one-fits-all",), ("personalized",)]
    assert counts == [(2, 1)]
    assert actions == [(1, "one-fits-all", 1, 2)]
    assert sys_messages == [
        (
            "moderation",
            2,
            "Your recent post violated the platform moderation policy. Please adjust your behavior.",
            1,
            4,
        )
    ]
    assert moderated == (1,)
    assert moderation_comment == (
        sys_messages[0][2],
        3,
        1,
        1,
        1,
    )


def test_personalized_moderator_requires_llm_model(tmp_path: Path) -> None:
    db_path = tmp_path / "simulation.db"
    agents_path = tmp_path / "agents.json"
    _build_db(db_path)
    _build_agents_json(agents_path)

    config = AppConfig(
        database=DatabaseConfig(sqlite_path=db_path, poll_interval_seconds=0.0),
        client=ClientConfig(
            client_id="moderator-client",
            agent_type="moderator",
            agents_json_path=agents_path,
            llm_servers=LLMServerConfig(values=_llm_servers()),
            simulation=SimulationConfig(
                days=30,
                slots=24,
                population_json_path=agents_path,
                raw=_simulation(tmp_path, agents_path),
            ),
            agent_settings=_moderator_settings(moderation_action_type="personalized"),
            max_ticks=1,
        ),
    )

    with pytest.raises(ValueError, match="requires a configured LangChain LLM model"):
        ClientApp(config).run()
