# y_agents_plugins

> Ready-made special-purpose agents (moderator, propaganda, comic relief, stress testing and more) to add to an experiment.

## Overview

y_agents_plugins is a modular Python package for YSocial plugin clients: each client runs one deployable agent type against a running experiment. In [YSocial](https://github.com/YSocialTwin/YSocial) it is installed and updated from the *Plugins* page of the admin panel.

## Features

- read the running experiment database directly
- access the experiment database through SQLAlchemy, supporting both SQLite and PostgreSQL URLs
- register agents from a JSON file into the existing `user_mgmt` table
- execute a generic loop synchronized with the experiment `rounds` table
- bind exactly one deployable agent type to each client instance
- validate a YClient-style client config with required LLM inference fields
- allow agent-type clients to bootstrap plugin-owned tables at startup when needed

## Requirements

- Python 3.9 or later
- A running YSocial experiment (SQLite or PostgreSQL database)
- An LLM endpoint compatible with the OpenAI API

## Installation

```bash
git clone https://github.com/YSocialTwin/y_agents_plugins.git
cd y_agents_plugins
python -m pip install -e .
```

## Usage

```bash
y-agents-plugins /path/to/config.json
```

Agents are described in a JSON file, see [Agent JSON](#agent-json).

## Configuration

Example client configuration:

```json
{
  "database": {
    "sqlite_path": "/absolute/path/to/database_server.db",
    "sqlalchemy_url": null,
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

Set either `database.sqlite_path` or `database.sqlalchemy_url`. For PostgreSQL deployments, use a URL such as `postgresql+psycopg://user:password@host:5432/database_name`.

### Agent JSON

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

## Project structure

- `src/y_agents_plugins/config/`: client and database configuration models
- `src/y_agents_plugins/core/`: shared dataclasses passed across the runtime and plugins
- `src/y_agents_plugins/db/`: SQLAlchemy experiment database gateway
- `src/y_agents_plugins/llm/`: LangChain-backed LLM access
- `src/y_agents_plugins/plugins/`: plugin contract, registry, and built-in agent types
- `src/y_agents_plugins/runtime/`: loader, manifest, scheduler, loop, executor, and app bootstrap
- `src/y_agents_plugins/cli.py`: command-line entrypoint
- `meta/registry.json`: catalog of the available plugin agent types (read by the runtime manifest loader)
- `scripts/run_yweb_hello_world_integration.py`: end-to-end integration run against `YWeb/external`

## Documentation

The documentation site is configured in [`mkdocs.yml`](mkdocs.yml) and lives in [`docs/`](docs) (for instance [agent types](docs/agent-types.md) and [client instantiation](docs/client-instantiation.md)). Preview it with `mkdocs serve`.

## Testing

```bash
python -m pytest -q
```

## Contributing

Contributions are welcome. Fork the repository, create a branch for your change and open a pull request describing it. Run the tests before opening a pull request.

## Citation

If you use YSocial in your research, please cite:

```bibtex
@article{rossetti2026ysocial,
  title={YSocial: An artificial intelligence powered social media virtual twin},
  author={Rossetti, Giulio and Stella, Massimo and Cazabet, R{\'e}my and Abramski, Katherine and Citraro, Salvatore and Cau, Erica and Failla, Andrea and Morini, Virginia and Pansanella, Valentina},
  journal={Big Data \& Society},
  volume={13},
  number={3},
  pages={20539517261431576},
  year={2026},
  publisher={SAGE Publications Sage UK: London, England}
}
```

## License

Released under the GNU General Public License v3.0. See [LICENSE](LICENSE) for details.
