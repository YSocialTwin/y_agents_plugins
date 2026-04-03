from __future__ import annotations

import logging

from y_agents_plugins.agent_loader import AgentSpecLoader
from y_agents_plugins.agent_types import load_agent_type_manifest
from y_agents_plugins.activity import ActivityProfileScheduler
from y_agents_plugins.agents import AgentTypeRegistry, HelloWorldAgent, ModeratorAgent
from y_agents_plugins.config import AppConfig
from y_agents_plugins.database import ExperimentDatabase
from y_agents_plugins.executor import ActionExecutor
from y_agents_plugins.loop import SimulationLoop
from y_agents_plugins.models import AgentAction


class ClientApp:
    """Bootstrap one client instance bound to exactly one agent type."""

    def __init__(
        self,
        config: AppConfig,
        *,
        registry: AgentTypeRegistry | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.agent_manifest = load_agent_type_manifest()
        self.registry = registry or build_default_registry()
        self.agent_manifest.require_known_agent_type(config.client.agent_type)
        self.agent = self.registry.create(
            config.client.agent_type,
            settings=config.client.agent_settings,
        )
        self.agent_loader = AgentSpecLoader()
        self.database = ExperimentDatabase(config.database.sqlite_path)
        self.executor = ActionExecutor(self.database)
        self.scheduler = ActivityProfileScheduler(config.client.simulation)
        self.loop = SimulationLoop(
            database=self.database,
            client_id=config.client.client_id,
            recent_posts_limit=config.client.recent_posts_limit,
            poll_interval_seconds=config.database.poll_interval_seconds,
            activity_filter=self.scheduler.is_active,
            logger=self.logger,
        )
        self.managed_agents = self.agent_loader.load(
            config.client.agents_json_path,
            expected_agent_type=config.client.agent_type,
        )
        for agent in self.managed_agents:
            config.client.simulation.is_agent_active(agent.activity_profile, 0)

    def run(self) -> list[AgentAction]:
        connection = self.database.connect()
        try:
            current_round = self.database.get_current_round(connection)
            self.database.register_agents(
                connection,
                self.managed_agents,
                joined_on=current_round.id,
            )
            return self.loop.run(
                self.agent.on_tick,
                managed_agents=self.managed_agents,
                action_sink=self.executor.execute,
                max_ticks=self.config.client.max_ticks,
                connection=connection,
            )
        finally:
            connection.close()


def build_default_registry() -> AgentTypeRegistry:
    registry = AgentTypeRegistry()
    registry.register(ModeratorAgent)
    registry.register(HelloWorldAgent)
    return registry
