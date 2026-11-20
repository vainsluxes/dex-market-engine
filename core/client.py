"""
DexScreener REST API Client — Synchronous & Asynchronous.

Provides rate-limited, retry-capable access to every public DexScreener
endpoint.  No authentication is required.
"""

from __future__ import annotations

import json
import time
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def _load_config() -> Dict[str, Any]:
    """Load and return the project configuration dictionary."""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Rate-limiter (token-bucket, shared by sync client)
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Simple sliding-window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window = window_seconds
        self._timestamps: list[float] = []

    def wait(self) -> None:
        """Block until a request slot is available."""
        now = time.monotonic()
        # Purge timestamps outside the window
        self._timestamps = [t for t in self._timestamps if now - t < self.window]
        if len(self._timestamps) >= self.max_requests:
            sleep_for = self.window - (now - self._timestamps[0]) + 0.05
            if sleep_for > 0:
                logger.debug("Rate-limit reached, sleeping %.2fs", sleep_for)
                time.sleep(sleep_for)
        self._timestamps.append(time.monotonic())


# ---------------------------------------------------------------------------
# Synchronous client
# ---------------------------------------------------------------------------

class DexScreenerClient:
    """Synchronous DexScreener REST client with automatic rate limiting."""

    MAX_RETRIES = 3
    RETRY_BACKOFF = 1.5  # seconds multiplied by attempt number

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.cfg = config or _load_config()
        self.base_url: str = self.cfg["api"]["base_url"]
        self.profiles_url: str = self.cfg["api"]["token_profiles_url"]
        self.boosts_url: str = self.cfg["api"]["token_boosts_url"]
        self.boosts_top_url: str = self.cfg["api"]["token_boosts_top_url"]
        self.supported_chains: List[str] = self.cfg["supported_chains"]
        rpm = self.cfg["rate_limits"]["requests_per_minute"]
        self._limiter = _RateLimiter(max_requests=rpm, window_seconds=60.0)
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "DexMarketEngine/1.0",
        })

    # -- low-level --------------------------------------------------------

    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET with rate-limiting and retries.  Returns parsed JSON."""
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            self._limiter.wait()
            try:
                resp = self._session.get(url, params=params, timeout=15)
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                last_exc = exc
                wait = self.RETRY_BACKOFF * attempt
                logger.warning(
                    "Request to %s failed (attempt %d/%d): %s — retrying in %.1fs",
                    url, attempt, self.MAX_RETRIES, exc, wait,
                )
                time.sleep(wait)
        raise RuntimeError(
            f"All {self.MAX_RETRIES} attempts to {url} failed"
        ) from last_exc

    # -- public API wrappers -----------------------------------------------

    def get_token_pairs(self, chain: str, token_address: str) -> Dict[str, Any]:
        """Return all DEX pairs that include *token_address*."""
        url = f"{self.base_url}/tokens/{token_address}"
        return self._get(url)

    def get_pairs_by_address(self, pair_address: str) -> Dict[str, Any]:
        """Return pair data given a pair contract address (multi-chain search)."""
        url = f"{self.base_url}/pairs/{pair_address}"
        return self._get(url)

    def search_pairs(self, query: str) -> Dict[str, Any]:
        """Free-text search for pairs by token name/symbol/address."""
        url = f"{self.base_url}/search"
        return self._get(url, params={"q": query})

    def get_token_profiles(self) -> Any:
        """Return latest token profile metadata."""
        return self._get(self.profiles_url)

    def get_token_boosts_top(self) -> Any:
        """Return the top-boosted tokens across all chains."""
        return self._get(self.boosts_top_url)

    def get_token_boosts(self) -> Any:
        """Return latest token boost events."""
        return self._get(self.boosts_url)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "DexScreenerClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Asynchronous client
# ---------------------------------------------------------------------------

class AsyncDexScreenerClient:
    """Async DexScreener REST client built on aiohttp."""

    MAX_RETRIES = 3
    RETRY_BACKOFF = 1.5

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.cfg = config or _load_config()
        self.base_url: str = self.cfg["api"]["base_url"]
        self.profiles_url: str = self.cfg["api"]["token_profiles_url"]
        self.boosts_url: str = self.cfg["api"]["token_boosts_url"]
        self.boosts_top_url: str = self.cfg["api"]["token_boosts_top_url"]
        self.supported_chains: List[str] = self.cfg["supported_chains"]
        self._rpm = self.cfg["rate_limits"]["requests_per_minute"]
        self._session: Optional[Any] = None
        self._timestamps: list[float] = []

    async def _ensure_session(self) -> Any:
        import aiohttp
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Accept": "application/json",
                    "User-Agent": "DexMarketEngine/1.0",
                },
                timeout=aiohttp.ClientTimeout(total=15),
            )
        return self._session

    async def _rate_limit(self) -> None:
        """Async-aware rate limiter using asyncio.sleep."""
        import asyncio
        now = time.monotonic()
        self._timestamps = [t for t in self._timestamps if now - t < 60.0]
        if len(self._timestamps) >= self._rpm:
            sleep_for = 60.0 - (now - self._timestamps[0]) + 0.05
            if sleep_for > 0:
                logger.debug("Async rate-limit reached, sleeping %.2fs", sleep_for)
                await asyncio.sleep(sleep_for)
        self._timestamps.append(time.monotonic())

    async def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        import asyncio
        import aiohttp
        session = await self._ensure_session()
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.MAX_RETRIES + 1):
            await self._rate_limit()
            try:
                async with session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    return await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                last_exc = exc
                wait = self.RETRY_BACKOFF * attempt
                logger.warning(
                    "Async request to %s failed (attempt %d/%d): %s",
                    url, attempt, self.MAX_RETRIES, exc,
                )
                await asyncio.sleep(wait)
        raise RuntimeError(
            f"All {self.MAX_RETRIES} async attempts to {url} failed"
        ) from last_exc

    # -- public API wrappers -----------------------------------------------

    async def get_token_pairs(self, chain: str, token_address: str) -> Dict[str, Any]:
        url = f"{self.base_url}/tokens/{token_address}"
        return await self._get(url)

    async def get_pairs_by_address(self, pair_address: str) -> Dict[str, Any]:
        url = f"{self.base_url}/pairs/{pair_address}"
        return await self._get(url)

    async def search_pairs(self, query: str) -> Dict[str, Any]:
        url = f"{self.base_url}/search"
        return await self._get(url, params={"q": query})

    async def get_token_profiles(self) -> Any:
        return await self._get(self.profiles_url)

    async def get_token_boosts_top(self) -> Any:
        return await self._get(self.boosts_top_url)

    async def get_token_boosts(self) -> Any:
        return await self._get(self.boosts_url)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> "AsyncDexScreenerClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()
