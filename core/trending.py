"""
Trending & Boosted Token Discovery — surface hot meme coins and
high-activity pairs across chains.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .client import DexScreenerClient
from .pairs import PairAnalyzer, PairData

logger = logging.getLogger(__name__)


class TrendingDiscovery:
    """Discover top-boosted and trending tokens across all supported DEXes."""

    def __init__(self, client: Optional[DexScreenerClient] = None):
        self.client = client or DexScreenerClient()

    # -----------------------------------------------------------------
    # Top Boosted
    # -----------------------------------------------------------------

    def get_top_boosted(self) -> List[Dict[str, Any]]:
        """Return raw top-boosted token entries from DexScreener."""
        try:
            data = self.client.get_token_boosts_top()
            if isinstance(data, list):
                return data
            return data if isinstance(data, list) else []
        except Exception as exc:
            logger.error("Failed to fetch top boosted tokens: %s", exc)
            return []

    # -----------------------------------------------------------------
    # Trending pairs (search-based heuristic)
    # -----------------------------------------------------------------

    def get_trending_pairs(
        self,
        chain: Optional[str] = None,
        min_liquidity: float = 1000.0,
        min_volume_24h: float = 500.0,
        limit: int = 25,
    ) -> List[PairData]:
        """
        Fetch top-boosted tokens, then enrich with pair data and apply
        liquidity / volume / chain filters.

        Returns a list of PairData sorted by 24 h volume descending.
        """
        boosted = self.get_top_boosted()
        pairs: List[PairData] = []

        for entry in boosted:
            token_address = entry.get("tokenAddress", "")
            entry_chain = entry.get("chainId", "")
            if not token_address or not entry_chain:
                continue
            if chain and entry_chain.lower() != chain.lower():
                continue
            try:
                raw = self.client.get_token_pairs(entry_chain, token_address)
                parsed = PairAnalyzer.parse_pairs(raw)
                for p in parsed:
                    # Apply filters
                    liq = p.liquidity.usd or 0
                    vol = p.volume.h24
                    if liq >= min_liquidity and vol >= min_volume_24h:
                        pairs.append(p)
            except Exception as exc:
                logger.warning(
                    "Could not fetch pairs for %s/%s: %s",
                    entry_chain, token_address, exc,
                )

        # Deduplicate by pair address, keep first occurrence
        seen: set[str] = set()
        unique: List[PairData] = []
        for p in pairs:
            if p.pair_address not in seen:
                seen.add(p.pair_address)
                unique.append(p)

        # Sort by 24 h volume descending
        unique.sort(key=lambda x: x.volume.h24, reverse=True)
        return unique[:limit]

    def search_trending(
        self,
        query: str = "meme",
        chain: Optional[str] = None,
        min_liquidity: float = 1000.0,
        min_volume_24h: float = 500.0,
        limit: int = 25,
    ) -> List[PairData]:
        """Search-based trending discovery with filters."""
        try:
            raw = self.client.search_pairs(query)
            parsed = PairAnalyzer.parse_pairs(raw)
        except Exception as exc:
            logger.error("Trending search failed: %s", exc)
            return []

        results: List[PairData] = []
        for p in parsed:
            if chain and p.chain_id.lower() != chain.lower():
                continue
            liq = p.liquidity.usd or 0
            vol = p.volume.h24
            if liq >= min_liquidity and vol >= min_volume_24h:
                results.append(p)

        results.sort(key=lambda x: x.volume.h24, reverse=True)
        return results[:limit]

    def close(self) -> None:
        self.client.close()
