from __future__ import annotations

import json
from pathlib import Path

from y_agents_plugins.models import AgentSpec


class AgentSpecLoader:
    """Load client-managed agents from JSON."""

    def load(self, path: str | Path, *, expected_agent_type: str) -> tuple[AgentSpec, ...]:
        payload = json.loads(Path(path).read_text())
        raw_agents = payload.get("agents", payload) if isinstance(payload, dict) else payload
        if not isinstance(raw_agents, list):
            raise ValueError("Agent JSON must contain a list or an 'agents' list")

        agents = tuple(self._parse_agent(entry) for entry in raw_agents)
        if not agents:
            raise ValueError("Agent JSON does not contain any agents")

        found_types = {agent.agent_type for agent in agents}
        if found_types != {expected_agent_type}:
            raise ValueError(
                f"Client '{expected_agent_type}' can only manage one agent type, found: {sorted(found_types)}"
            )
        return agents

    def _parse_agent(self, entry: dict) -> AgentSpec:
        if not isinstance(entry, dict):
            raise ValueError("Each agent entry must be an object")

        username = entry.get("username", entry.get("name"))
        if not username:
            raise ValueError("Agent entry missing 'username' or 'name'")
        name = entry.get("name", username)

        email = entry.get("email")
        if not email:
            raise ValueError(f"Agent '{username}' missing 'email'")

        agent_type = entry.get("agent_type", entry.get("user_type"))
        if not agent_type:
            raise ValueError(f"Agent '{username}' missing 'agent_type' or 'user_type'")
        if "activity_profile" not in entry:
            raise ValueError(f"Agent '{username}' missing 'activity_profile'")
        if "daily_budget" not in entry:
            raise ValueError(f"Agent '{username}' missing 'daily_budget'")

        known_keys = {
            "username",
            "name",
            "email",
            "password",
            "pwd",
            "agent_type",
            "user_type",
            "joined_on",
            "leaning",
            "interests",
            "age",
            "oe",
            "co",
            "ex",
            "ag",
            "ne",
            "recsys_type",
            "frecsys_type",
            "language",
            "owner",
            "education_level",
            "activity_profile",
            "daily_budget",
            "parameters",
        }
        extra_parameters = dict(entry.get("parameters", {}))
        for key, value in entry.items():
            if key not in known_keys:
                extra_parameters[key] = value

        return AgentSpec(
            name=str(name),
            username=str(username),
            email=str(email),
            password=str(entry.get("password", entry.get("pwd", "changeme"))),
            agent_type=str(agent_type),
            activity_profile=str(entry["activity_profile"]),
            daily_budget=float(entry["daily_budget"]),
            joined_on=int(entry.get("joined_on", 0)),
            leaning=entry.get("leaning"),
            interests=_normalize_interests(entry.get("interests")),
            age=_optional_int(entry.get("age")),
            oe=_optional_str(entry.get("oe")),
            co=_optional_str(entry.get("co")),
            ex=_optional_str(entry.get("ex")),
            ag=_optional_str(entry.get("ag")),
            ne=_optional_str(entry.get("ne")),
            recsys_type=_optional_str(entry.get("recsys_type")),
            frecsys_type=_optional_str(entry.get("frecsys_type")),
            language=_optional_str(entry.get("language")),
            owner=_optional_str(entry.get("owner")),
            education_level=_optional_str(entry.get("education_level")),
            parameters=extra_parameters,
        )


def _optional_int(value):
    return None if value is None else int(value)


def _optional_str(value):
    return None if value is None else str(value)


def _normalize_interests(value):
    if value is None:
        return None
    if isinstance(value, list):
        return json.dumps(value)
    return str(value)
