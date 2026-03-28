"""
Async scheduler for SF City Intelligence scraper agents.

Runs two classes of agents concurrently using asyncio:
  - Live agents (IS_LIVE=True): polled on a fixed interval (e.g. every 5 min)
  - Static agents (IS_LIVE=False): run once on startup, then once every 24 h

All agents run independently — a failure in one never blocks the others.
Graceful shutdown is handled via asyncio.Event (SIGINT / SIGTERM).

Usage:
    scheduler = Scheduler(agents)
    await scheduler.run()
"""

import asyncio
import logging
import signal
from typing import Sequence

from agents.base import BaseAgent

logger = logging.getLogger(__name__)


class Scheduler:
    """Coordinates all scraper agents with independent async loops.

    Args:
        agents: All agent instances to manage.
        live_interval: Override the interval (seconds) for live agents.
            Defaults to each agent's own INTERVAL_SECONDS.
        static_interval: Override the interval (seconds) for static agents.
            Defaults to 86400 (daily).

    Example:
        scheduler = Scheduler([AirNowAgent(), SF311Agent(), YelpAgent()])
        await scheduler.run()
    """

    def __init__(
        self,
        agents: Sequence[BaseAgent],
        live_interval: int | None = None,
        static_interval: int | None = None,
    ) -> None:
        self._agents = list(agents)
        self._live_interval = live_interval
        self._static_interval = static_interval
        self._stop = asyncio.Event()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start all agent loops and block until a stop signal is received."""
        self._install_signal_handlers()

        live = [a for a in self._agents if a.IS_LIVE]
        static = [a for a in self._agents if not a.IS_LIVE]

        logger.info(
            "Scheduler starting: %d live agents, %d static agents",
            len(live), len(static),
        )

        tasks = []
        for agent in live:
            interval = self._live_interval or agent.INTERVAL_SECONDS
            tasks.append(asyncio.create_task(
                self._live_loop(agent, interval),
                name=f"live:{agent.AGENT_ID}",
            ))

        for agent in static:
            interval = self._static_interval or 86400
            tasks.append(asyncio.create_task(
                self._static_loop(agent, interval),
                name=f"static:{agent.AGENT_ID}",
            ))

        # Block until a stop signal is received
        await self._stop.wait()

        logger.info("Scheduler: stop signal received — cancelling agent tasks")
        for task in tasks:
            task.cancel()

        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Scheduler: all agent tasks stopped cleanly")

    def stop(self) -> None:
        """Signal the scheduler to stop all loops after current runs complete."""
        self._stop.set()

    # ------------------------------------------------------------------
    # Agent loops
    # ------------------------------------------------------------------

    async def _live_loop(self, agent: BaseAgent, interval: int) -> None:
        """Poll a live agent repeatedly at a fixed interval."""
        logger.info("Live loop started: %s (every %ds)", agent.AGENT_ID, interval)
        while not self._stop.is_set():
            await self._safe_run(agent)
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop.wait()), timeout=interval
                )
            except asyncio.TimeoutError:
                pass  # interval elapsed — run again

    async def _static_loop(self, agent: BaseAgent, interval: int) -> None:
        """Run a static agent on startup, then once every `interval` seconds."""
        logger.info("Static loop started: %s (every %ds)", agent.AGENT_ID, interval)
        while not self._stop.is_set():
            await self._safe_run(agent)
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop.wait()), timeout=interval
                )
            except asyncio.TimeoutError:
                pass  # interval elapsed — run again

    @staticmethod
    async def _safe_run(agent: BaseAgent) -> None:
        """Run one agent cycle, catching and logging all exceptions."""
        try:
            await agent.run_once()
        except asyncio.CancelledError:
            raise  # let cancellation propagate
        except Exception as e:
            logger.error("Scheduler: unhandled error in %s: %s", agent.AGENT_ID, e, exc_info=True)

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Register SIGINT and SIGTERM to trigger a graceful stop."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop)
            except (NotImplementedError, RuntimeError):
                # Windows or environments that don't support add_signal_handler
                pass
