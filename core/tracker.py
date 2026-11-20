"""
Live Token Tracker — poll a token's price and volume at a fixed interval,
compute deltas, and feed data to the CLI's live-updating display.
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .client import DexScreenerClient
from .pairs import PairAnalyzer, PairData

logger = logging.getLogger(__name__)


@dataclass
class Snapshot:
    """A single point-in-time capture of token metrics."""
    timestamp: float
    price_usd: Optional[float]
    volume_24h: float
    liquidity_usd: Optional[float]
    market_cap: Optional[float]
    txns_buys_24h: int
    txns_sells_24h: int
    price_change_5m: Optional[float] = None
    price_change_1h: Optional[float] = None
    price_change_24h: Optional[float] = None


@dataclass
class Delta:
    """Computed change between two consecutive snapshots."""
    seconds_elapsed: float = 0.0
    price_change_abs: Optional[float] = None
    price_change_pct: Optional[float] = None
    volume_change: float = 0.0
    new_buys: int = 0
    new_sells: int = 0


class TokenTracker:
    """
    Continuously polls DexScreener for a token, records snapshots,
    and computes deltas between consecutive polls.
    """

    def __init__(
        self,
        token_address: str,
        chain: str = "solana",
        interval: float = 5.0,
        client: Optional[DexScreenerClient] = None,
    ):
        self.token_address = token_address
        self.chain = chain
        self.interval = max(1.0, interval)
        self.client = client or DexScreenerClient()
        self.history: List[Snapshot] = []
        self._running = False

    def _fetch_best_pair(self) -> Optional[PairData]:
        """Fetch pairs for the token and return the one with highest liquidity."""
        try:
            raw = self.client.get_token_pairs(self.chain, self.token_address)
            pairs = PairAnalyzer.parse_pairs(raw)
            if not pairs:
                return None
            # Pick pair with highest liquidity
            pairs.sort(key=lambda p: p.liquidity.usd or 0, reverse=True)
            return pairs[0]
        except Exception as exc:
            logger.error("Tracker fetch failed: %s", exc)
            return None

    def take_snapshot(self) -> Optional[Snapshot]:
        """Capture a single snapshot of the token's best pair."""
        pair = self._fetch_best_pair()
        if pair is None:
            return None
        snap = Snapshot(
            timestamp=time.time(),
            price_usd=pair.price_usd,
            volume_24h=pair.volume.h24,
            liquidity_usd=pair.liquidity.usd,
            market_cap=pair.market_cap,
            txns_buys_24h=pair.txns.h24.buys,
            txns_sells_24h=pair.txns.h24.sells,
            price_change_5m=pair.price_change.m5,
            price_change_1h=pair.price_change.h1,
            price_change_24h=pair.price_change.h24,
        )
        self.history.append(snap)
        return snap

    def compute_delta(self) -> Optional[Delta]:
        """Compute the delta between the last two snapshots."""
        if len(self.history) < 2:
            return None
        prev, curr = self.history[-2], self.history[-1]
        delta = Delta(seconds_elapsed=curr.timestamp - prev.timestamp)

        if curr.price_usd is not None and prev.price_usd is not None:
            delta.price_change_abs = curr.price_usd - prev.price_usd
            if prev.price_usd != 0:
                delta.price_change_pct = (
                    (curr.price_usd - prev.price_usd) / prev.price_usd * 100
                )

        delta.volume_change = curr.volume_24h - prev.volume_24h
        delta.new_buys = curr.txns_buys_24h - prev.txns_buys_24h
        delta.new_sells = curr.txns_sells_24h - prev.txns_sells_24h
        return delta

    def run(
        self,
        callback: Callable[[Snapshot, Optional[Delta]], bool],
        max_iterations: int = 0,
    ) -> None:
        """
        Main polling loop.

        *callback* is called with (snapshot, delta).  If it returns False the
        loop stops.  *max_iterations* of 0 means unlimited.
        """
        self._running = True
        iteration = 0
        try:
            while self._running:
                snap = self.take_snapshot()
                if snap is None:
                    logger.warning("No data — will retry in %.0fs", self.interval)
                    time.sleep(self.interval)
                    continue
                delta = self.compute_delta()
                if not callback(snap, delta):
                    break
                iteration += 1
                if max_iterations and iteration >= max_iterations:
                    break
                time.sleep(self.interval)
        except KeyboardInterrupt:
            logger.info("Tracker stopped by user")
        finally:
            self._running = False

    def stop(self) -> None:
        """Signal the run-loop to exit."""
        self._running = False

    def close(self) -> None:
        self.client.close()
