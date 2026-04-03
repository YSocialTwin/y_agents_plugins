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
            shared_from INTEGER DEFAULT -1
        );
        INSERT INTO rounds (day, hour) VALUES (0, 0);
        INSERT INTO user_mgmt (id, username, email, password, user_type, owner, joined_on)
        VALUES (1, 'alice', 'alice@example.org', 'secret', 'human', 'experiment', 1);
        INSERT INTO post (id, tweet, user_id, round) VALUES (1, 'hello world', 1, 1);
        """
    )
    connection.commit()
    connection.close()


def _build_agents_json(path: Path, *, agent_type: str = "moderator") -> None:
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
                    "parameters": {"toxicity_keywords": ["abuse"]},
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
            agent_settings={"toxicity_keywords": ["abuse"]},
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
