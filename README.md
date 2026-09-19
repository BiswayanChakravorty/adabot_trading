# Trading Agent (free, no Telegram)

A market-scanning agent for Indian indices + major crypto using free data sources and free hosting. It logs candidate trade ideas that pass a deterministic risk filter; it does not place trades.

## Setup
```bash
pip install -r requirements.txt
export GROQ_API_KEY="your-key"
python trading_agent.py
```

Optional Gmail alerts use `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO`, and `ALERT_EMAIL_PASSWORD` (a Gmail app password).

## GitHub Actions
The included workflow runs hourly and can also be triggered manually. Add `GROQ_API_KEY` under **Settings → Secrets and variables → Actions**. Add the email secrets only when email alerts are needed.

Workflow path: `.github/workflows/run_agent.yml`

## Watchlists
Edit `STOCK_WATCHLIST` and `CRYPTO_WATCHLIST` in `trading_agent.py`. `ENABLE_STOCKS = False` keeps the current Phase 1 scope to crypto; set it to `True` to include the configured Indian indices.

## Risk controls
- Total capital: INR 3,000
- Per-trade allocation: INR 1,000
- Target: 10% of allocated capital
- Maximum allowed loss: 3% of allocated capital
- Minimum reward:risk ratio: 2.0

The LLM proposes a candidate, while the Python risk layer independently calculates quantity, target, stop-loss, and pass/fail.

## Expectations
This is a market-scanning and journaling tool, not a guaranteed-profit system. Treat logged signals as candidates for your own review, not instructions to trade. The agent does not place trades.
