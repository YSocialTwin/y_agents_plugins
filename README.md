# y_agents_plugins

Modular Python skeleton for YSocial plugin clients that:

- read the running experiment database directly
- register agents from a JSON file into the existing `user_mgmt` table
- execute a generic loop synchronized with the experiment `rounds` table
- bind exactly one deployable agent type to each client instance
- validate a YClient-style client config with required LLM inference fields

## Current structure

- `src/y_agents_plugins/database.py`: direct SQLite gateway for `rounds`, `user_mgmt`, and `post`
- `src/y_agents_plugins/agent_loader.py`: JSON loader for client-managed agent definitions
- `src/y_agents_plugins/loop.py`: generic synchronized simulation loop
- `src/y_agents_plugins/agents/base.py`: plugin contract and registry
- `src/y_agents_plugins/agents/hello_world.py`: simple hourly posting agent
- `src/y_agents_plugins/agents/moderator.py`: sample moderator implementation
- `src/y_agents_plugins/runtime.py`: client bootstrap enforcing one agent type per process
- `src/y_agents_plugins/cli.py`: minimal entrypoint
- `plugins_exposed/agent_types.json`: catalog of available plugin agent types
- `scripts/run_yweb_hello_world_integration.py`: end-to-end integration run against `YWeb/external`

Full documentation site: see `mkdocs.yml` and the `docs/` directory, or run `mkdocs serve`.

## Example config

```json
{
  "database": {
    "sqlite_path": "/absolute/path/to/database_server.db",
    "poll_interval_seconds": 1.0
  },
  "client": {
    "client_id": "moderator-client-01",
    "agent_type": "moderator",
    "agents_json_path": "/absolute/path/to/agents.json",
    "servers": {
      "llm": "http://127.0.0.1:11434/v1",
      "llm_api_key": "NULL",
      "llm_max_tokens": -1,
      "llm_temperature": 1.5,
      "llm_v": "http://127.0.0.1:11434/v1",
      "llm_v_api_key": "NULL",
      "llm_v_max_tokens": 300,
      "llm_v_temperature": 0.5,
      "api": "http://127.0.0.1:5001/"
    },
    "simulation": {
      "days": 30,
      "slots": 24,
      "population_json_path": "/absolute/path/to/agents.json"
    },
    "agents": {
      "llm_v_agent": "minicpm-v:latest",
      "reading_from_follower_ratio": 0.6,
      "max_length_thread_reading": 10
    },
    "agent_settings": {
      "toxicity_keywords": ["hate", "idiot", "stupid"]
    },
    "recent_posts_limit": 25,
    "max_ticks": 10
  }
}
```

## Agent JSON

The client accepts either a raw list or an object with an `agents` list. Each entry is mapped only onto fields already present in YSocial `user_mgmt`; extra keys remain in memory as plugin parameters and are not written to new tables.

```json
[
  {
    "name": "Moderator One",
    "username": "mod_1",
    "email": "mod_1@example.org",
    "password": "secret",
    "agent_type": "moderator",
    "activity_profile": "Always On",
    "daily_budget": 42,
    "language": "en",
    "parameters": {
      "toxicity_keywords": ["hate", "idiot", "stupid"]
    }
  }
]
```

Required per-agent fields:

- `name`
- `activity_profile`
- `daily_budget`

Required client-level fields:

- all LLM inference/server fields used by YClient-style configs: `llm`, `llm_api_key`, `llm_max_tokens`, `llm_temperature`, `llm_v`, `llm_v_api_key`, `llm_v_max_tokens`, `llm_v_temperature`, `api`
- simulation length in `simulation.days`
- rounds per day in `simulation.slots`
- population JSON path in `simulation.population_json_path`

## Run

```bash
python -m pip install -e .
y-agents-plugins /path/to/config.json
```
