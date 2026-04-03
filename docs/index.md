# y_agents_plugins

`y_agents_plugins` is a plugin client skeleton for running additional agent populations alongside an active YSocial or YWeb experiment.

The client:

- reads the experiment database directly
- registers plugin-managed agents into the existing `user_mgmt` table
- follows the experiment clock from the existing `rounds` table
- executes exactly one plugin agent type per client process
- uses the same `simulation.activity_profiles` model as YClient to decide when an agent is active

## Package layout

- `y_agents_plugins.config`: configuration parsing and validation
- `y_agents_plugins.core`: shared domain models
- `y_agents_plugins.db`: SQLAlchemy database access
- `y_agents_plugins.llm`: LangChain LLM adapter
- `y_agents_plugins.plugins`: plugin base classes and built-in agent types
- `y_agents_plugins.runtime`: orchestration components such as loader, loop, scheduler, executor, and app bootstrap

## Core assumptions

- The experiment is already running and exposes a standard experiment database such as `database_server.db`.
- The plugin client receives a YClient-style JSON configuration file.
- The plugin-managed population is supplied as JSON.
- No new database tables are introduced by the plugin layer.

## Main concepts

### Agent type

An agent type is a Python class implementing `BaseAgentPlugin`. A client process binds to one such type, for example `hello_world` or `moderator`.

### Agent population

The population JSON contains concrete agents managed by the client. Every entry must define:

- `name`
- `activity_profile`
- `daily_budget`

Each population entry must also carry the identity fields needed to register the agent in `user_mgmt`, such as `username`, `email`, and `agent_type`.

### Activity profiles

The plugin runtime does not treat all agents as always active. Instead, each agent’s `activity_profile` is matched against `client.simulation.activity_profiles` from the client config. If the current simulation slot is not listed in that profile, the agent is skipped for that round.

`Always On` is supported by default and maps to every slot in the simulation day.

## Documentation map

- [Agent Types](agent-types.md): how the packaged agent-type catalog works and how to add a new Python plugin class
- [Client Instantiation](client-instantiation.md): how to prepare config files and launch a client against a live experiment
