from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REQUIRED_LLM_SERVER_FIELDS = (
    "llm",
    "llm_api_key",
    "llm_max_tokens",
    "llm_temperature",
    "llm_v",
    "llm_v_api_key",
    "llm_v_max_tokens",
    "llm_v_temperature",
    "api",
)


@dataclass(frozen=True)
class DatabaseConfig:
    sqlite_path: Path | None = None
    sqlalchemy_url: str | None = None
    poll_interval_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.sqlite_path is None and not self.sqlalchemy_url:
            raise ValueError("database config requires either sqlite_path or sqlalchemy_url")

    @property
    def url(self) -> str:
        if self.sqlalchemy_url:
            return self.sqlalchemy_url
        assert self.sqlite_path is not None
        return f"sqlite:///{self.sqlite_path}"


@dataclass(frozen=True)
class LLMServerConfig:
    values: dict[str, Any]

    def __post_init__(self) -> None:
        missing = [field for field in REQUIRED_LLM_SERVER_FIELDS if field not in self.values]
        if missing:
            raise ValueError(f"Client config missing LLM/server fields: {missing}")


@dataclass(frozen=True)
class SimulationConfig:
    days: int
    slots: int
    population_json_path: Path
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.days <= 0:
            raise ValueError("simulation.days must be > 0")
        if self.slots <= 0:
            raise ValueError("simulation.slots must be > 0")

    @property
    def activity_profiles(self) -> dict[str, tuple[int, ...]]:
        raw_profiles = self.raw.get("activity_profiles") or {}
        profiles: dict[str, tuple[int, ...]] = {
            "Always On": tuple(range(self.slots)),
        }
        for name, raw_slots in raw_profiles.items():
            profile_name = str(name).strip()
            if not profile_name:
                raise ValueError("simulation.activity_profiles contains an empty profile name")
            slots = _parse_activity_profile_slots(raw_slots, slots_per_day=self.slots)
            profiles[profile_name] = slots
        return profiles

    def is_agent_active(self, activity_profile: str, slot: int) -> bool:
        try:
            allowed_slots = self.activity_profiles[activity_profile]
        except KeyError as exc:
            known = ", ".join(sorted(self.activity_profiles))
            raise ValueError(
                f"Unknown activity_profile '{activity_profile}'. Known profiles: {known}"
            ) from exc
        return slot in allowed_slots


@dataclass(frozen=True)
class ClientConfig:
    client_id: str
    agent_type: str
    llm_servers: LLMServerConfig
    simulation: SimulationConfig
    agents_json_path: Path | None = None
    agents_settings: dict[str, Any] = field(default_factory=dict)
    agent_settings: dict[str, Any] = field(default_factory=dict)
    recent_posts_limit: int = 25
    max_ticks: int | None = None

    def __post_init__(self) -> None:
        if not self.client_id.strip():
            raise ValueError("client_id must be a non-empty string")
        if not self.agent_type.strip():
            raise ValueError("agent_type must be a non-empty string")
        if self.agents_json_path is None:
            object.__setattr__(
                self,
                "agents_json_path",
                self.simulation.population_json_path,
            )

    @property
    def primary_llm_model(self) -> str | None:
        agent_model = self.agent_settings.get("llm_model")
        if agent_model:
            return str(agent_model)
        configured_models = self.agents_settings.get("llm_agents")
        if isinstance(configured_models, list):
            for model in configured_models:
                if model:
                    return str(model)
        return None


@dataclass(frozen=True)
class AppConfig:
    database: DatabaseConfig
    client: ClientConfig

    @classmethod
    def from_file(cls, path: str | Path) -> "AppConfig":
        raw = json.loads(Path(path).read_text())
        database = raw.get("database", {})
        client = raw.get("client", {})
        simulation = client.get("simulation", {})
        return cls(
            database=DatabaseConfig(
                sqlite_path=(
                    Path(database["sqlite_path"]).expanduser().resolve()
                    if database.get("sqlite_path") is not None
                    else None
                ),
                sqlalchemy_url=database.get("sqlalchemy_url"),
                poll_interval_seconds=float(database.get("poll_interval_seconds", 1.0)),
            ),
            client=ClientConfig(
                client_id=client["client_id"],
                agent_type=client["agent_type"],
                agents_json_path=(
                    Path(client["agents_json_path"]).expanduser().resolve()
                    if client.get("agents_json_path") is not None
                    else None
                ),
                llm_servers=LLMServerConfig(values=dict(client["servers"])),
                simulation=SimulationConfig(
                    days=int(simulation["days"]),
                    slots=int(simulation["slots"]),
                    population_json_path=Path(simulation["population_json_path"])
                    .expanduser()
                    .resolve(),
                    raw=dict(simulation),
                ),
                agents_settings=dict(client.get("agents", {})),
                agent_settings=dict(client.get("agent_settings", {})),
                recent_posts_limit=int(client.get("recent_posts_limit", 25)),
                max_ticks=(
                    int(client["max_ticks"])
                    if client.get("max_ticks") is not None
                    else None
                ),
            ),
        )


def _parse_activity_profile_slots(raw_value: Any, *, slots_per_day: int) -> tuple[int, ...]:
    if isinstance(raw_value, str):
        values = [chunk.strip() for chunk in raw_value.split(",") if chunk.strip()]
    elif isinstance(raw_value, (list, tuple)):
        values = list(raw_value)
    else:
        raise ValueError("Activity profile slots must be a comma-separated string or a list")

    parsed_slots: list[int] = []
    for value in values:
        slot = int(value)
        if slot < 0 or slot >= slots_per_day:
            raise ValueError(
                f"Activity profile slot '{slot}' is outside the valid range 0-{slots_per_day - 1}"
            )
        parsed_slots.append(slot)

    unique_slots = tuple(sorted(set(parsed_slots)))
    if not unique_slots:
        raise ValueError("Activity profile must contain at least one valid slot")
    return unique_slots
