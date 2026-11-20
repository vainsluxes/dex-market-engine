"""
Pair Analytics — extract and structure detailed token pair data from
DexScreener API responses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models for strict validation
# ---------------------------------------------------------------------------

class TokenInfo(BaseModel):
    """Base or quote token metadata."""
    address: str = ""
    name: str = ""
    symbol: str = ""

class PriceChanges(BaseModel):
    """Percentage price changes across multiple time windows."""
    m5: Optional[float] = Field(None, description="5-minute price change %")
    h1: Optional[float] = Field(None, description="1-hour price change %")
    h6: Optional[float] = Field(None, description="6-hour price change %")
    h24: Optional[float] = Field(None, description="24-hour price change %")

class VolumeBreakdown(BaseModel):
    """Volume in USD across multiple time windows."""
    m5: float = 0.0
    h1: float = 0.0
    h6: float = 0.0
    h24: float = 0.0

class TxCounts(BaseModel):
    """Buy and sell transaction counts for a time window."""
    buys: int = 0
    sells: int = 0

class TxBreakdown(BaseModel):
    """Transaction counts across time windows."""
    m5: TxCounts = Field(default_factory=TxCounts)
    h1: TxCounts = Field(default_factory=TxCounts)
    h6: TxCounts = Field(default_factory=TxCounts)
    h24: TxCounts = Field(default_factory=TxCounts)

class LiquidityInfo(BaseModel):
    """Liquidity pool size."""
    usd: Optional[float] = None
    base: float = 0.0
    quote: float = 0.0


class PairData(BaseModel):
    """Comprehensive analytics for a single DEX pair."""
    chain_id: str = ""
    dex_id: str = ""
    pair_address: str = ""
    url: str = ""

    base_token: TokenInfo = Field(default_factory=TokenInfo)
    quote_token: TokenInfo = Field(default_factory=TokenInfo)

    price_usd: Optional[float] = None
    price_native: Optional[str] = None
    fdv: Optional[float] = None
    market_cap: Optional[float] = None

    price_change: PriceChanges = Field(default_factory=PriceChanges)
    volume: VolumeBreakdown = Field(default_factory=VolumeBreakdown)
    txns: TxBreakdown = Field(default_factory=TxBreakdown)
    liquidity: LiquidityInfo = Field(default_factory=LiquidityInfo)

    pair_created_at: Optional[int] = None

    @property
    def buy_sell_ratio_24h(self) -> Optional[float]:
        """Buy-to-sell transaction ratio over 24 h (None if no sells)."""
        if self.txns.h24.sells == 0:
            return None
        return self.txns.h24.buys / self.txns.h24.sells

    @property
    def buy_volume_ratio_24h(self) -> Optional[str]:
        """Human-readable buy vs sell transaction summary for 24 h."""
        b = self.txns.h24.buys
        s = self.txns.h24.sells
        total = b + s
        if total == 0:
            return "N/A"
        return f"{b}/{s} ({b / total * 100:.0f}% buys)"


# ---------------------------------------------------------------------------
# Analyzer: raw JSON ➜ PairData
# ---------------------------------------------------------------------------

class PairAnalyzer:
    """Extracts and normalises pair data from DexScreener JSON payloads."""

    @staticmethod
    def _parse_txns(raw: Dict[str, Any]) -> TxBreakdown:
        """Parse the nested txns dict into a TxBreakdown model."""
        def _tc(d: Any) -> TxCounts:
            if not d or not isinstance(d, dict):
                return TxCounts()
            return TxCounts(buys=int(d.get("buys", 0)), sells=int(d.get("sells", 0)))
        return TxBreakdown(
            m5=_tc(raw.get("m5")),
            h1=_tc(raw.get("h1")),
            h6=_tc(raw.get("h6")),
            h24=_tc(raw.get("h24")),
        )

    @staticmethod
    def _parse_volume(raw: Dict[str, Any]) -> VolumeBreakdown:
        if not raw or not isinstance(raw, dict):
            return VolumeBreakdown()
        return VolumeBreakdown(
            m5=float(raw.get("m5", 0) or 0),
            h1=float(raw.get("h1", 0) or 0),
            h6=float(raw.get("h6", 0) or 0),
            h24=float(raw.get("h24", 0) or 0),
        )

    @staticmethod
    def _parse_price_change(raw: Dict[str, Any]) -> PriceChanges:
        if not raw or not isinstance(raw, dict):
            return PriceChanges()
        def _flt(v: Any) -> Optional[float]:
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        return PriceChanges(
            m5=_flt(raw.get("m5")),
            h1=_flt(raw.get("h1")),
            h6=_flt(raw.get("h6")),
            h24=_flt(raw.get("h24")),
        )

    @staticmethod
    def _parse_liquidity(raw: Dict[str, Any]) -> LiquidityInfo:
        if not raw or not isinstance(raw, dict):
            return LiquidityInfo()
        return LiquidityInfo(
            usd=raw.get("usd"),
            base=float(raw.get("base", 0) or 0),
            quote=float(raw.get("quote", 0) or 0),
        )

    @classmethod
    def parse_pair(cls, raw: Dict[str, Any]) -> PairData:
        """Convert a single raw pair dict into a validated PairData."""
        base = raw.get("baseToken") or {}
        quote = raw.get("quoteToken") or {}
        price_usd_raw = raw.get("priceUsd")
        try:
            price_usd = float(price_usd_raw) if price_usd_raw is not None else None
        except (TypeError, ValueError):
            price_usd = None

        return PairData(
            chain_id=raw.get("chainId", ""),
            dex_id=raw.get("dexId", ""),
            pair_address=raw.get("pairAddress", ""),
            url=raw.get("url", ""),
            base_token=TokenInfo(
                address=base.get("address", ""),
                name=base.get("name", ""),
                symbol=base.get("symbol", ""),
            ),
            quote_token=TokenInfo(
                address=quote.get("address", ""),
                name=quote.get("name", ""),
                symbol=quote.get("symbol", ""),
            ),
            price_usd=price_usd,
            price_native=raw.get("priceNative"),
            fdv=raw.get("fdv"),
            market_cap=raw.get("marketCap"),
            price_change=cls._parse_price_change(raw.get("priceChange", {})),
            volume=cls._parse_volume(raw.get("volume", {})),
            txns=cls._parse_txns(raw.get("txns", {})),
            liquidity=cls._parse_liquidity(raw.get("liquidity", {})),
            pair_created_at=raw.get("pairCreatedAt"),
        )

    @classmethod
    def parse_pairs(cls, payload: Dict[str, Any]) -> List[PairData]:
        """Parse the top-level API response and return a list of PairData."""
        pairs_raw = payload.get("pairs") or payload.get("pair") or []
        if isinstance(pairs_raw, dict):
            pairs_raw = [pairs_raw]
        results: List[PairData] = []
        for p in pairs_raw:
            try:
                results.append(cls.parse_pair(p))
            except Exception as exc:
                logger.warning("Skipping malformed pair: %s", exc)
        return results
