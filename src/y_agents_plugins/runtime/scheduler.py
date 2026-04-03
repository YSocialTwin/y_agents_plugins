from __future__ import annotations

from y_agents_plugins.config import SimulationConfig
from y_agents_plugins.core import AgentSpec, SimulationRound


class ActivityProfileScheduler:
    """Resolve whether an agent should run for the current simulation slot."""

    def __init__(self, simulation: SimulationConfig) -> None:
        self.simulation = simulation

    def is_active(self, agent: AgentSpec, current_round: SimulationRound) -> bool:
        return self.simulation.is_agent_active(agent.activity_profile, current_round.slot)
