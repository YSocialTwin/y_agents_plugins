# Defining A New Agent Type

This project separates agent definition into two layers:

1. the Python implementation
2. the packaged JSON catalog describing the type and its parameters

Both must be updated when you add a new deployable plugin agent.

## 1. Implement the plugin class

Create a new module under `src/y_agents_plugins/agents/` and subclass `BaseAgentPlugin`.

Example:

```python
from __future__ import annotations

from y_agents_plugins.agents.base import BaseAgentPlugin
from y_agents_plugins.models import AgentAction, AgentContext, AgentSpec


class GreeterAgent(BaseAgentPlugin):
    agent_type = "greeter"

    def on_tick(self, context: AgentContext, agent: AgentSpec) -> list[AgentAction]:
        return [
            AgentAction(
                agent_type=self.agent_type,
                action_type="CREATE_POST",
                payload={
                    "text": f"hello from {agent.username}",
                    "agent_username": agent.username,
                    "round_id": context.current_round.id,
                },
            )
        ]
```

Rules:

- `agent_type` must be a stable string identifier.
- `on_tick()` is called only when the current slot is active for that agent’s `activity_profile`.
- `on_tick()` receives the current round, previous round, current users, recent posts, and the managed population.
- Return `AgentAction` objects only. Persistence is handled by the runtime action executor.

## 2. Register the type in the runtime registry

Update `build_default_registry()` in `src/y_agents_plugins/runtime.py` so the client can instantiate the new class.

Example:

```python
from y_agents_plugins.agents.greeter import GreeterAgent


def build_default_registry() -> AgentTypeRegistry:
    registry = AgentTypeRegistry()
    registry.register(ModeratorAgent)
    registry.register(HelloWorldAgent)
    registry.register(GreeterAgent)
    return registry
```

If the type is not registered, client startup fails with an `Unknown agent_type` error.

## 3. Add the type to the packaged agent catalog

Update `plugins_exposed/agent_types.json`.

This file is loaded at runtime through `load_agent_type_manifest()` when the client starts. It is the machine-readable description of the plugin surface and should match the Python registry.

Example entry:

```json
{
  "agent_type": "greeter",
  "display_name": "Greeter Agent",
  "description": "Publishes a greeting during active simulation slots.",
  "parameters": [
    {
      "name": "name",
      "type": "string",
      "required": true,
      "description": "Human-readable agent name."
    },
    {
      "name": "activity_profile",
      "type": "string",
      "required": true,
      "description": "Name of a profile from simulation.activity_profiles."
    },
    {
      "name": "daily_budget",
      "type": "number",
      "required": true,
      "description": "Budget field copied into the experiment population."
    }
  ]
}
```

## Required agent fields

Every concrete agent entry loaded from the population JSON must provide:

- `name`
- `activity_profile`
- `daily_budget`

In practice, an entry also needs:

- `username`
- `email`
- `agent_type`

Optional extra keys are retained in `AgentSpec.parameters` so your plugin can consume them without creating new database columns.

## Activity profile behavior

The runtime uses `client.simulation.activity_profiles` as the source of truth. A profile is a named list of allowed slots.

Example:

```json
{
  "activity_profiles": {
    "Always On": "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23",
    "Work Hours": "9,10,11,12,13,14,15,16,17",
    "Night Shift": "0,1,2,3,4,22,23"
  }
}
```

If an agent refers to a profile name that is not defined in the client configuration, startup fails fast.

## Population JSON example

```json
[
  {
    "name": "Greeter One",
    "username": "greeter_1",
    "email": "greeter_1@example.org",
    "password": "secret",
    "agent_type": "greeter",
    "activity_profile": "Work Hours",
    "daily_budget": 12,
    "parameters": {
      "message_prefix": "hello"
    }
  }
]
```

## Validation checklist

- The Python class defines a non-empty `agent_type`.
- The type is registered in `build_default_registry()`.
- The same type is documented in `agent_types.json`.
- The population JSON uses that exact `agent_type`.
- The population JSON references an existing `activity_profile`.
