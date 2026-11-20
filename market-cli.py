#!/usr/bin/env python3
"""
market-cli.py — Rich terminal interface for the DexScreener Multi-DEX
Real-Time Market Intelligence Engine.

Subcommands
-----------
  token   <chain> <token_address>             Comprehensive token analytics
  search  <query>                              Search tokens by name/symbol
  trending [--chain <chain>]                   Top boosted & trending tokens
  watch   <token_address> [--chain] [--interval]  Live price tracker
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.columns import Columns
from rich.layout import Layout

from core.client import DexScreenerClient
from core.pairs import PairAnalyzer, PairData
from core.trending import TrendingDiscovery
from core.tracker import TokenTracker, Snapshot, Delta

console = Console()


# ── Helpers ──────────────────────────────────────────────────────────────

def _fmt_usd(value: Optional[float], compact: bool = False) -> str:
    """Format a USD value for display."""
    if value is None:
        return "[dim]N/A[/dim]"
    if compact and abs(value) >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.2f}B"
    if compact and abs(value) >= 1_000_000:
        return f"${value / 1_000_000:,.2f}M"
    if compact and abs(value) >= 1_000:
        return f"${value / 1_000:,.2f}K"
    if value < 0.01 and value > 0:
        return f"${value:.8f}"
    return f"${value:,.4f}"


def _fmt_pct(value: Optional[float]) -> str:
    """Format a percentage with colour."""
    if value is None:
        return "[dim]N/A[/dim]"
    colour = "green" if value >= 0 else "red"
    arrow = "▲" if value >= 0 else "▼"
    return f"[{colour}]{arrow} {value:+.2f}%[/{colour}]"


def _fmt_int(value: int) -> str:
    return f"{value:,}"


def _short_addr(addr: str, n: int = 6) -> str:
    if len(addr) <= n * 2 + 2:
        return addr
    return f"{addr[:n]}…{addr[-n:]}"


# ── Subcommand: token ───────────────────────────────────────────────────

def cmd_token(args: argparse.Namespace) -> None:
    """Display comprehensive analytics for a token on a given chain."""
    with DexScreenerClient() as client:
        console.print(f"\n[bold cyan]Fetching pairs for[/] [yellow]{args.token_address}[/] on [magenta]{args.chain}[/]…\n")
        raw = client.get_token_pairs(args.chain, args.token_address)

    pairs = PairAnalyzer.parse_pairs(raw)
    if not pairs:
        console.print("[red]No pairs found for this token / chain combination.[/red]")
        sys.exit(1)

    # Show the best pair (highest liquidity) in a detail panel
    pairs.sort(key=lambda p: p.liquidity.usd or 0, reverse=True)
    best = pairs[0]

    # ── Price & market panel ──
    lines = [
        f"[bold white]{best.base_token.name}[/] ([cyan]{best.base_token.symbol}[/]) / {best.quote_token.symbol}",
        "",
        f"  💰 Price USD        {_fmt_usd(best.price_usd)}",
        f"  📈 Price Native     {best.price_native or 'N/A'}",
        f"  🏦 Market Cap       {_fmt_usd(best.market_cap, compact=True)}",
        f"  💎 FDV              {_fmt_usd(best.fdv, compact=True)}",
        f"  💧 Liquidity        {_fmt_usd(best.liquidity.usd, compact=True)}",
        "",
        "  [bold underline]Price Changes[/]",
        f"    5 min   {_fmt_pct(best.price_change.m5)}",
        f"    1 hr    {_fmt_pct(best.price_change.h1)}",
        f"    6 hr    {_fmt_pct(best.price_change.h6)}",
        f"   24 hr    {_fmt_pct(best.price_change.h24)}",
    ]
    console.print(Panel("\n".join(lines), title="📊 Token Overview", border_style="cyan", expand=False))

    # ── Volume breakdown ──
    vol_table = Table(title="📦 Volume Breakdown (USD)", show_header=True, header_style="bold magenta")
    vol_table.add_column("Window", style="cyan")
    vol_table.add_column("Volume", justify="right")
    vol_table.add_row("5 min",  _fmt_usd(best.volume.m5, compact=True))
    vol_table.add_row("1 hr",   _fmt_usd(best.volume.h1, compact=True))
    vol_table.add_row("6 hr",   _fmt_usd(best.volume.h6, compact=True))
    vol_table.add_row("24 hr",  _fmt_usd(best.volume.h24, compact=True))
    console.print(vol_table)

    # ── Buy/Sell tx breakdown ──
    tx_table = Table(title="🔄 Buy vs Sell Transactions", show_header=True, header_style="bold green")
    tx_table.add_column("Window", style="cyan")
    tx_table.add_column("Buys", justify="right", style="green")
    tx_table.add_column("Sells", justify="right", style="red")
    tx_table.add_column("Ratio", justify="right")
    for label, tc in [("5 min", best.txns.m5), ("1 hr", best.txns.h1),
                       ("6 hr", best.txns.h6), ("24 hr", best.txns.h24)]:
        total = tc.buys + tc.sells
        ratio = f"{tc.buys / total * 100:.0f}% buys" if total else "N/A"
        tx_table.add_row(label, _fmt_int(tc.buys), _fmt_int(tc.sells), ratio)
    console.print(tx_table)

    # ── Pair info ──
    info_lines = [
        f"  🔗 DEX              [yellow]{best.dex_id}[/yellow]",
        f"  ⛓️  Chain            [magenta]{best.chain_id}[/magenta]",
        f"  📍 Pair Address     [dim]{best.pair_address}[/dim]",
        f"  🌐 DexScreener      [link={best.url}]{best.url}[/link]",
    ]
    console.print(Panel("\n".join(info_lines), title="ℹ️  Pair Details", border_style="yellow", expand=False))

    # If there are multiple pairs, show a summary table
    if len(pairs) > 1:
        multi = Table(title=f"📋 All Pairs ({len(pairs)})", show_header=True, header_style="bold blue")
        multi.add_column("#", style="dim")
        multi.add_column("DEX")
        multi.add_column("Quote")
        multi.add_column("Price", justify="right")
        multi.add_column("Liq.", justify="right")
        multi.add_column("Vol 24h", justify="right")
        multi.add_column("Pair", style="dim")
        for i, p in enumerate(pairs[:15], 1):
            multi.add_row(
                str(i),
                p.dex_id,
                p.quote_token.symbol,
                _fmt_usd(p.price_usd),
                _fmt_usd(p.liquidity.usd, compact=True),
                _fmt_usd(p.volume.h24, compact=True),
                _short_addr(p.pair_address),
            )
        console.print(multi)


# ── Subcommand: search ──────────────────────────────────────────────────

def cmd_search(args: argparse.Namespace) -> None:
    """Search for tokens by name, symbol, or address."""
    with DexScreenerClient() as client:
        console.print(f"\n[bold cyan]Searching for[/] [yellow]{args.query}[/]…\n")
        raw = client.search_pairs(args.query)

    pairs = PairAnalyzer.parse_pairs(raw)
    if not pairs:
        console.print("[red]No results found.[/red]")
        sys.exit(1)

    table = Table(
        title=f"🔍 Search Results for '{args.query}' ({len(pairs)} pairs)",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Token", min_width=12)
    table.add_column("Chain", style="magenta")
    table.add_column("DEX")
    table.add_column("Price", justify="right")
    table.add_column("24h Δ", justify="right")
    table.add_column("Vol 24h", justify="right")
    table.add_column("Liq.", justify="right")
    table.add_column("MCap", justify="right")

    for i, p in enumerate(pairs[:30], 1):
        table.add_row(
            str(i),
            f"{p.base_token.symbol} / {p.quote_token.symbol}",
            p.chain_id,
            p.dex_id,
            _fmt_usd(p.price_usd),
            _fmt_pct(p.price_change.h24),
            _fmt_usd(p.volume.h24, compact=True),
            _fmt_usd(p.liquidity.usd, compact=True),
            _fmt_usd(p.market_cap, compact=True),
        )

    console.print(table)


# ── Subcommand: trending ────────────────────────────────────────────────

def cmd_trending(args: argparse.Namespace) -> None:
    """Show top-boosted and trending tokens across DEXes."""
    chain = getattr(args, "chain", None)
    label = f" on [magenta]{chain}[/magenta]" if chain else " across all chains"
    console.print(f"\n[bold cyan]Fetching trending tokens{label}…[/]\n")

    discovery = TrendingDiscovery()
    try:
        pairs = discovery.get_trending_pairs(chain=chain, limit=30)
    finally:
        discovery.close()

    if not pairs:
        console.print("[yellow]No trending tokens matched the filters. Trying search fallback…[/yellow]\n")
        discovery2 = TrendingDiscovery()
        try:
            pairs = discovery2.search_trending(query="token", chain=chain, limit=30)
        finally:
            discovery2.close()

    if not pairs:
        console.print("[red]No trending data available right now.[/red]")
        sys.exit(1)

    table = Table(
        title=f"🔥 Trending Tokens ({len(pairs)})",
        show_header=True,
        header_style="bold yellow",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Token", min_width=10)
    table.add_column("Chain", style="magenta")
    table.add_column("DEX")
    table.add_column("Price", justify="right")
    table.add_column("24h Δ", justify="right")
    table.add_column("Vol 24h", justify="right")
    table.add_column("Liq.", justify="right")
    table.add_column("MCap", justify="right")

    for i, p in enumerate(pairs, 1):
        table.add_row(
            str(i),
            f"{p.base_token.symbol}",
            p.chain_id,
            p.dex_id,
            _fmt_usd(p.price_usd),
            _fmt_pct(p.price_change.h24),
            _fmt_usd(p.volume.h24, compact=True),
            _fmt_usd(p.liquidity.usd, compact=True),
            _fmt_usd(p.market_cap, compact=True),
        )

    console.print(table)


# ── Subcommand: watch ───────────────────────────────────────────────────

def cmd_watch(args: argparse.Namespace) -> None:
    """Live-updating token price & volume tracker."""
    chain = getattr(args, "chain", None) or "solana"
    interval = getattr(args, "interval", 5) or 5

    console.print(
        f"\n[bold cyan]Watching[/] [yellow]{args.token_address}[/] on "
        f"[magenta]{chain}[/] every [green]{interval}s[/green]  "
        f"(Ctrl+C to stop)\n"
    )

    tracker = TokenTracker(
        token_address=args.token_address,
        chain=chain,
        interval=interval,
    )

    def _build_display(snap: Snapshot, delta: Optional[Delta]) -> Table:
        """Build the Rich table for a single live frame."""
        t = Table(
            title=f"👁  Live Tracker — {_short_addr(args.token_address)} on {chain}",
            show_header=False,
            expand=False,
            border_style="cyan",
            title_style="bold cyan",
        )
        t.add_column("Metric", style="bold white", min_width=22)
        t.add_column("Value", justify="right", min_width=24)
        t.add_column("Delta", justify="right", min_width=20)

        # Price
        price_delta = ""
        if delta and delta.price_change_abs is not None:
            colour = "green" if delta.price_change_abs >= 0 else "red"
            pct = delta.price_change_pct or 0
            price_delta = f"[{colour}]{delta.price_change_abs:+.8f} ({pct:+.4f}%)[/{colour}]"
        t.add_row("💰 Price USD", _fmt_usd(snap.price_usd), price_delta)

        # Volume
        vol_delta = ""
        if delta:
            colour = "green" if delta.volume_change >= 0 else "red"
            vol_delta = f"[{colour}]{delta.volume_change:+,.0f}[/{colour}]"
        t.add_row("📦 Volume 24h", _fmt_usd(snap.volume_24h, compact=True), vol_delta)

        # Liquidity
        t.add_row("💧 Liquidity", _fmt_usd(snap.liquidity_usd, compact=True), "")

        # Market Cap
        t.add_row("🏦 Market Cap", _fmt_usd(snap.market_cap, compact=True), "")

        # Txns
        buy_delta = ""
        sell_delta = ""
        if delta:
            if delta.new_buys:
                buy_delta = f"[green]+{delta.new_buys}[/green]"
            if delta.new_sells:
                sell_delta = f"[red]+{delta.new_sells}[/red]"
        t.add_row("🟢 Buys 24h", _fmt_int(snap.txns_buys_24h), buy_delta)
        t.add_row("🔴 Sells 24h", _fmt_int(snap.txns_sells_24h), sell_delta)

        # API price changes
        t.add_row("📈 5m change", _fmt_pct(snap.price_change_5m), "")
        t.add_row("📈 1h change", _fmt_pct(snap.price_change_1h), "")
        t.add_row("📈 24h change", _fmt_pct(snap.price_change_24h), "")

        # Timestamp
        ts = time.strftime("%H:%M:%S", time.localtime(snap.timestamp))
        polls = len(tracker.history)
        t.add_row("🕐 Updated", ts, f"[dim]poll #{polls}[/dim]")

        return t

    with Live(console=console, refresh_per_second=2, transient=False) as live:
        def _callback(snap: Snapshot, delta: Optional[Delta]) -> bool:
            display = _build_display(snap, delta)
            live.update(display)
            return True  # keep running

        try:
            tracker.run(callback=_callback)
        except KeyboardInterrupt:
            pass
        finally:
            tracker.close()

    console.print("\n[dim]Tracker stopped.[/dim]")


# ── Argument parser ─────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="market-cli",
        description="DexScreener Multi-DEX Real-Time Market Intelligence Engine",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # token
    p_token = sub.add_parser("token", help="Comprehensive token analytics")
    p_token.add_argument("chain", help="Blockchain (solana, base, bsc, ethereum, polygon, arbitrum, avalanche)")
    p_token.add_argument("token_address", help="Token contract address")

    # search
    p_search = sub.add_parser("search", help="Search tokens by name or symbol")
    p_search.add_argument("query", help="Search query (symbol, name, or address)")

    # trending
    p_trending = sub.add_parser("trending", help="Top boosted & trending tokens")
    p_trending.add_argument("--chain", default=None, help="Filter by chain")

    # watch
    p_watch = sub.add_parser("watch", help="Live token price tracker")
    p_watch.add_argument("token_address", help="Token contract address")
    p_watch.add_argument("--chain", default="solana", help="Blockchain (default: solana)")
    p_watch.add_argument("--interval", type=int, default=5, help="Polling interval in seconds (default: 5)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "token": cmd_token,
        "search": cmd_search,
        "trending": cmd_trending,
        "watch": cmd_watch,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
