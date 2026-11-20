# DexScreener & Multi-DEX Real-Time Market Intelligence Engine

High-speed zero-auth token search, liquidity analytics, price tracking, trending lists, and pair intelligence across Solana, Base, BSC, Ethereum, Polygon, Arbitrum.

## Architecture

```
dex-market-engine/
├── requirements.txt     # requests, pydantic, rich, aiohttp
├── config.json          # Rate limits, cached chains, alert thresholds
├── core/
│   ├── client.py        # DexScreener REST API client (300 req/min, zero auth)
│   ├── pairs.py         # Pair details, volume, buy/sell ratios, liquidity depth
│   ├── trending.py      # Trending / Boosted tokens discovery
│   └── tracker.py       # Multi-token price & volume change watcher
├── market-cli.py        # Rich CLI interface (price, search, trending, watch, pair)
└── venv/                # Python virtualenv
```

## Commands

```bash
# Setup venv and install dependencies
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# Get token price, market cap, and liquidity across all DEX pairs
venv/bin/python market-cli.py token <chain: solana|base|bsc|ethereum> <token_address>

# Search tokens by symbol or name
venv/bin/python market-cli.py search <query>

# Get top trending / boosted tokens
venv/bin/python market-cli.py trending [--chain solana]

# Watch token prices with live terminal updates
venv/bin/python market-cli.py watch <token_address> [--interval 5]
```

## Conventions
- Zero Authentication required. 300 requests/minute default rate limit.
- All code, comments, log lines, and documentation must be written in English.
