# Instantiating A Client

Each client process manages exactly one plugin agent type and follows the same experiment clock as the main simulation.

## Required inputs

You need three things:

1. the running experiment database path
2. a YClient-style client configuration JSON
3. a population JSON containing only agents of the selected plugin type

## Client configuration structure

The plugin client expects a wrapper config with `database` and `client` sections.

Example:

```json
{
  "database": {
    "sqlite_path": "/absolute/path/to/database_server.db",
    "poll_interval_seconds": 1.0
  },
  "client": {
    "client_id": "hello-world-client",
    "agent_type": "hello_world",
    "agents_json_path": "/absolute/path/to/hello_world_agents.json",
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
      "days": 10,
      "slots": 24,
      "population_json_path": "/absolute/path/to/hello_world_agents.json",
      "activity_profiles": {
        "Always On": "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23",
        "Work Hours": "9,10,11,12,13,14,15,16,17"
      }
    },
    "agent_settings": {},
    "recent_posts_limit": 25
  }
}
```

## Required client fields

### LLM and server fields

The `client.servers` object must contain the fields normally present in YClient-generated configs:

- `llm`
- `llm_api_key`
- `llm_max_tokens`
- `llm_temperature`
- `llm_v`
- `llm_v_api_key`
- `llm_v_max_tokens`
- `llm_v_temperature`
- `api`

These are validated even if a given plugin agent type does not call the LLM yet. This keeps the plugin config shape aligned with YClient.

### Stress/reward configuration

If the experiment uses stress/reward, the plugin client can also receive a top-level or mirrored `stress_reward` block. The runtime normalizes that configuration and exposes it to the executor so plugin-generated posts, comments, reactions, shares, and moderation actions can update the same `stress_reward` table used by the standard clients.

This matters in particular for agents such as:

- `stress_attacker`
- `comic_relief`
- `moderator`
- `propaganda`
- `master_of_puppets`

### Simulation fields

The `client.simulation` object must contain:

- `days`
- `slots`
- `population_json_path`

`activity_profiles` is also strongly recommended and is used to control when plugin-managed agents are active. If omitted, `Always On` is available implicitly for all slots.

## Population file

The population JSON can be either:

- a raw list of agent objects
- an object containing an `agents` list

All agents in that file must share the same `agent_type`, and that type must match `client.agent_type`.

Example:

```json
[
  {
    "name": "Hello World Bot",
    "username": "helloworldbot",
    "email": "helloworldbot@example.org",
    "password": "secret",
    "agent_type": "hello_world",
    "activity_profile": "Always On",
    "daily_budget": 24
  }
]
```

For LLM-backed agents, the population and client config may also carry agent-type-specific prompt overrides. Examples include:

- `llm_prompt_override` for `stress_attacker` and `moderator`
- `opening_llm_prompt_override` and `reply_llm_prompt_override` for `comic_relief`
- `opening_llm_prompt_override` and `reply_llm_prompt_override` for `propaganda`

These overrides replace the built-in system prompts entirely rather than appending instructions to them.

## Startup sequence

When the client starts, it performs these steps:

1. load and validate the client configuration
2. load the packaged `agent_types.json` catalog
3. instantiate the selected Python plugin class
4. load and validate the agent population JSON
5. verify every agent’s `activity_profile` exists in `simulation.activity_profiles`
6. connect to the running experiment database
7. register the agents in the existing `user_mgmt` table
8. poll `rounds` and execute one synchronized tick per unseen round

## Synchronization behavior

The client follows the experiment clock from the database instead of advancing time itself.

For each unseen row in `rounds`:

- it builds an `AgentContext`
- it filters the managed population by `activity_profile`
- it calls the plugin only for agents active in that slot
- it persists supported actions, such as `CREATE_POST`, into existing experiment tables

This means the plugin client remains aligned with the simulation server and with any standard YClient process running at the same time.

## Running the client

Install the package in editable mode and start it with the config path:

```bash
python -m pip install -e .
y-agents-plugins /absolute/path/to/plugin_config.json
```

Or:

```bash
python -m y_agents_plugins.cli /absolute/path/to/plugin_config.json
```

## Common failure modes

### Unknown agent type

Cause: `client.agent_type` is not registered in Python or not listed in `agent_types.json`.

### Mixed population types

Cause: the population JSON contains agents with more than one `agent_type`.

### Unknown activity profile

Cause: an agent’s `activity_profile` is not defined in `client.simulation.activity_profiles`.

### Missing LLM fields

Cause: the config does not mirror the YClient server section closely enough.

### Stress/reward agent without experiment support

Cause: an agent type such as `stress_attacker` is being instantiated against an experiment that does not expose stress/reward in the generated config. In that case, the plugin may still load, but the stress-specific behaviors will not have the required downstream state.
