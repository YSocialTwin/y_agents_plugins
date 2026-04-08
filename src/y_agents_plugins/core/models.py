from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SimulationRound:
    """Database-backed representation of the current experiment round."""

    id: int
    day: int
    slot: int


@dataclass(frozen=True)
class UserRecord:
    id: int
    username: str
    user_type: str | None = None
    owner: str | None = None
    profile: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PostRecord:
    id: int
    author_id: int
    text: str
    round_id: int
    comment_to: int | None = None
    thread_id: int | None = None
    shared_from: int | None = None
    moderated: int = 0
    toxicity: float | None = None
    reported_count: int = 0


@dataclass(frozen=True)
class AgentAction:
    """Generic action envelope produced by plugin agents."""

    agent_type: str
    action_type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentContext:
    """Per-tick context passed to the bound agent implementation."""

    client_id: str
    current_round: SimulationRound
    previous_round: SimulationRound | None
    users: tuple[UserRecord, ...]
    recent_posts: tuple[PostRecord, ...]
    managed_agents: tuple["AgentSpec", ...]
    connection: Any | None = None


@dataclass(frozen=True)
class AgentSpec:
    """Agent definition loaded from JSON and mapped onto `user_mgmt` fields."""

    name: str
    username: str
    email: str
    password: str
    agent_type: str
    activity_profile: str
    daily_budget: float
    joined_on: int = 0
    leaning: str | None = None
    interests: str | None = None
    age: int | None = None
    oe: str | None = None
    co: str | None = None
    ex: str | None = None
    ag: str | None = None
    ne: str | None = None
    recsys_type: str | None = None
    frecsys_type: str | None = None
    language: str | None = None
    owner: str | None = None
    education_level: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
