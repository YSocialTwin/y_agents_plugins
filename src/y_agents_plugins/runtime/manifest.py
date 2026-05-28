from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentTypeParameter:
    name: str
    type: str
    required: bool
    description: str


@dataclass(frozen=True)
class AgentTypeDescription:
    agent_type: str
    display_name: str
    description: str
    parameters: tuple[AgentTypeParameter, ...]


class AgentTypeManifest:
    def __init__(self, agent_types: dict[str, AgentTypeDescription]) -> None:
        self.agent_types = dict(agent_types)

    def require_known_agent_type(self, agent_type: str) -> AgentTypeDescription:
        try:
            return self.agent_types[agent_type]
        except KeyError as exc:
            known = ", ".join(sorted(self.agent_types)) or "<none>"
            raise ValueError(f"Unknown agent_type '{agent_type}'. Known types: {known}") from exc


def load_agent_type_manifest() -> AgentTypeManifest:
    raw = json.loads(_manifest_path().read_text(encoding="utf-8"))
    descriptions: dict[str, AgentTypeDescription] = {}
    for entry in raw["agent_types"]:
        parameters = tuple(
            AgentTypeParameter(
                name=str(parameter["name"]),
                type=str(parameter["type"]),
                required=bool(parameter["required"]),
                description=str(parameter["description"]),
            )
            for parameter in entry.get("parameters", [])
        )
        description = AgentTypeDescription(
            agent_type=str(entry["agent_type"]),
            display_name=str(entry.get("display_name", entry["agent_type"])),
            description=str(entry["description"]),
            parameters=parameters,
        )
        descriptions[description.agent_type] = description
    return AgentTypeManifest(descriptions)


def _manifest_path() -> Path:
    base = Path(__file__).resolve().parents[3]
    candidates = (
        base / "meta" / "registry.json",
        base / "plugins_exposed" / "agent_types.json",
        base / "plugin_exposed" / "agent_types.json",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]
