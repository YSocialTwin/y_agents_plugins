from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from y_agents_plugins.db import ExperimentDatabase

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec


class BaseAgentPlugin(ABC):
    """Base contract for one deployable agent type bound to a client instance."""

    agent_type: str
    _PLUGIN_USER_TYPES = {
        "hello_world",
        "moderator",
        "propaganda",
        "master_of_puppets",
        "mop_puppet",
        "stress_attacker",
        "comic_relief",
    }

    def __init__(self, settings: dict | None = None, llm_client=None):
        self.settings = dict(settings or {})
        self.llm = llm_client
        self.database = None

    def setup_database(
        self,
        database: "ExperimentDatabase",
        connection: "Connection",
    ) -> None:
        """Create or seed plugin-owned schema objects before the loop starts."""
        self.database = database

    @abstractmethod
    def on_tick(self, context: AgentContext, agent: AgentSpec) -> list[AgentAction]:
        """Run one simulation step in sync with the experiment loop."""

    @classmethod
    def _is_plugin_user(cls, user) -> bool:
        return (
            str(getattr(user, "user_type", "") or "").strip().lower()
            in cls._PLUGIN_USER_TYPES
        )


class AgentTypeRegistry:
    """Registry of available plugin agent types."""

    def __init__(self) -> None:
        self._registry: dict[str, type[BaseAgentPlugin]] = {}

    def register(self, agent_class: type[BaseAgentPlugin]) -> None:
        agent_type = getattr(agent_class, "agent_type", "").strip()
        if not agent_type:
            raise ValueError("Registered agent class must define a non-empty agent_type")
        self._registry[agent_type] = agent_class

    def create(self, agent_type: str, settings: dict | None = None, llm_client=None) -> BaseAgentPlugin:
        try:
            agent_class = self._registry[agent_type]
        except KeyError as exc:
            known = ", ".join(sorted(self._registry)) or "<none>"
            raise ValueError(f"Unknown agent_type '{agent_type}'. Known types: {known}") from exc
        return agent_class(settings=settings, llm_client=llm_client)

    @property
    def supported_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._registry))
