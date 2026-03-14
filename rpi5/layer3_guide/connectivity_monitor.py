"""
Connectivity Monitor — Real-time network health checker

Checks ACTUAL connectivity to laptop server and Gemini Live API.
Never infers connectivity from location — always measures.

4-level scale:
  FULL (4)         — Gemini Live connected, laptop WS latency <200ms
  DEGRADED (3)     — Laptop reachable, latency <1s, Gemini may be down
  INTERMITTENT (2) — Laptop reachable but slow (>1s)
  OFFLINE (1)      — No connectivity at all

Author: Haziq (@IRSPlays)
Date: March 14, 2026
"""

import asyncio
import logging
import time
from enum import IntEnum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class ConnectivityLevel(IntEnum):
    OFFLINE = 1
    INTERMITTENT = 2
    DEGRADED = 3
    FULL = 4


class ConnectivityMonitor:
    """Check REAL connectivity. Never infer from location."""

    def __init__(
        self,
        ws_client=None,
        gemini_handler=None,
        tts=None,
        check_interval: float = 3.0,
        on_level_change: Optional[Callable] = None,
    ):
        self.ws_client = ws_client
        self.gemini_handler = gemini_handler
        self.tts = tts
        self.check_interval = check_interval
        self.on_level_change = on_level_change

        self.level = ConnectivityLevel.FULL
        self._previous_level = ConnectivityLevel.FULL
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_announce_time = 0.0

    @property
    def is_online(self) -> bool:
        return self.level >= ConnectivityLevel.DEGRADED

    @property
    def is_offline(self) -> bool:
        return self.level == ConnectivityLevel.OFFLINE

    async def start(self):
        """Start the connectivity monitoring loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("✅ ConnectivityMonitor started")

    async def stop(self):
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ConnectivityMonitor stopped")

    async def _check_loop(self):
        """Main monitoring loop — checks every N seconds."""
        while self._running:
            try:
                await self._measure()
            except Exception as e:
                logger.debug(f"Connectivity check error: {e}")
            await asyncio.sleep(self.check_interval)

    async def _measure(self):
        """Measure actual connectivity from real checks."""
        laptop_ok = False
        laptop_latency = float('inf')
        gemini_ok = False

        # Test 1: Laptop server reachable?
        if self.ws_client and hasattr(self.ws_client, 'is_connected'):
            laptop_ok = self.ws_client.is_connected
            if laptop_ok and hasattr(self.ws_client, 'last_latency'):
                laptop_latency = self.ws_client.last_latency or 0.5

        # Test 2: Gemini Live connected?
        if self.gemini_handler:
            gemini_ok = getattr(self.gemini_handler, 'is_connected', False)

        # Determine level from MEASUREMENTS, not assumptions
        if gemini_ok and laptop_latency < 0.2:
            new_level = ConnectivityLevel.FULL
        elif laptop_ok and laptop_latency < 1.0:
            new_level = ConnectivityLevel.DEGRADED
        elif laptop_ok:
            new_level = ConnectivityLevel.INTERMITTENT
        else:
            new_level = ConnectivityLevel.OFFLINE

        # Handle level changes
        if new_level != self.level:
            old_level = self.level
            self.level = new_level
            logger.info(f"📡 Connectivity: {old_level.name} → {new_level.name}")

            # Announce significant changes via TTS
            now = time.time()
            if now - self._last_announce_time > 10.0:  # Don't spam
                await self._announce_change(old_level, new_level)
                self._last_announce_time = now

            # Fire callback
            if self.on_level_change:
                try:
                    self.on_level_change(new_level, old_level)
                except Exception as e:
                    logger.debug(f"Level change callback error: {e}")

        self._previous_level = self.level

    async def _announce_change(self, old: ConnectivityLevel, new: ConnectivityLevel):
        """Announce connectivity changes via TTS."""
        if not self.tts:
            return

        if new == ConnectivityLevel.OFFLINE and old >= ConnectivityLevel.DEGRADED:
            await self.tts.speak_async(
                "I've lost connection. Don't worry, I'm still guiding you."
            )
        elif new >= ConnectivityLevel.DEGRADED and old == ConnectivityLevel.OFFLINE:
            await self.tts.speak_async(
                "I'm back online."
            )
        elif new == ConnectivityLevel.INTERMITTENT and old >= ConnectivityLevel.DEGRADED:
            await self.tts.speak_async(
                "Connection is weak. Some features may be slower."
            )

    def get_context_string(self) -> str:
        """Return context string for Gemini injection."""
        return f"[CONNECTIVITY] {self.level.name}"
