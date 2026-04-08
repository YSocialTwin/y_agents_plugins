from __future__ import annotations

import logging
import time
from collections.abc import Callable

from sqlalchemy import Connection

from y_agents_plugins.core import AgentAction, AgentContext, AgentSpec, SimulationRound
from y_agents_plugins.db import ExperimentDatabase


class SimulationLoop:
    """Poll the experiment database and execute one synchronized tick per new round."""

    def __init__(
        self,
        *,
        database: ExperimentDatabase,
        client_id: str,
        recent_posts_limit: int = 25,
        poll_interval_seconds: float = 1.0,
        activity_filter: Callable[[AgentSpec, SimulationRound], bool] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.database = database
        self.client_id = client_id
        self.recent_posts_limit = recent_posts_limit
        self.poll_interval_seconds = poll_interval_seconds
        self.activity_filter = activity_filter or (lambda agent, current_round: True)
        self.logger = logger or logging.getLogger(__name__)

    def run(
        self,
        tick_handler: Callable[[AgentContext, AgentSpec], list[AgentAction]],
        *,
        managed_agents: tuple[AgentSpec, ...],
        action_sink: Callable[[Connection, AgentContext, AgentSpec, AgentAction], None] | None = None,
        max_ticks: int | None = None,
        connection: Connection | None = None,
    ) -> list[AgentAction]:
        own_connection = connection is None
        connection = connection or self.database.connect()
        emitted_actions: list[AgentAction] = []
        ticks = 0
        previous_round: SimulationRound | None = None
        last_seen_round_id: int | None = None

        try:
            while max_ticks is None or ticks < max_ticks:
                pending_rounds = self.database.get_rounds_after(connection, last_seen_round_id)
                if not pending_rounds:
                    time.sleep(self.poll_interval_seconds)
                    continue

                for current_round in pending_rounds:
                    if max_ticks is not None and ticks >= max_ticks:
                        break

                    context = AgentContext(
                        client_id=self.client_id,
                        current_round=current_round,
                        previous_round=previous_round,
                        users=self.database.get_users(connection),
                        recent_posts=self.database.get_recent_posts(
                            connection,
                            round_id=current_round.id,
                            limit=self.recent_posts_limit,
                        ),
                        managed_agents=managed_agents,
                        connection=connection,
                    )

                    self.logger.info(
                        "Executing synchronized tick",
                        extra={
                            "client_id": self.client_id,
                            "round_id": current_round.id,
                            "day": current_round.day,
                            "slot": current_round.slot,
                            "managed_agents": len(managed_agents),
                        },
                    )
                    for agent in managed_agents:
                        if not self.activity_filter(agent, current_round):
                            self.logger.debug(
                                "Skipping inactive agent for current slot",
                                extra={
                                    "client_id": self.client_id,
                                    "round_id": current_round.id,
                                    "agent_username": agent.username,
                                    "activity_profile": agent.activity_profile,
                                    "slot": current_round.slot,
                                },
                            )
                            continue
                        actions = tick_handler(context, agent)
                        emitted_actions.extend(actions)
                        if action_sink is not None:
                            for action in actions:
                                action_sink(
                                    connection,
                                    context=context,
                                    agent=agent,
                                    action=action,
                                )
                    previous_round = current_round
                    last_seen_round_id = current_round.id
                    ticks += 1

            return emitted_actions
        finally:
            if own_connection:
                connection.close()
