from y_agents_plugins.plugins.base import AgentTypeRegistry, BaseAgentPlugin
from y_agents_plugins.plugins.comic_relief import ComicReliefAgent
from y_agents_plugins.plugins.hello_world import HelloWorldAgent
from y_agents_plugins.plugins.master_of_puppets import MasterOfPuppetsAgent
from y_agents_plugins.plugins.moderator import ModeratorAgent
from y_agents_plugins.plugins.propaganda import PropagandaAgent
from y_agents_plugins.plugins.stress_attacker import StressAttackerAgent

__all__ = [
    "AgentTypeRegistry",
    "BaseAgentPlugin",
    "ComicReliefAgent",
    "HelloWorldAgent",
    "MasterOfPuppetsAgent",
    "ModeratorAgent",
    "PropagandaAgent",
    "StressAttackerAgent",
]
