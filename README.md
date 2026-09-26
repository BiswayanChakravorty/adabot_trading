# AdaBot Crypto — Crypto-Only Market Scanner

AdaBot Crypto is dedicated to digital-asset markets. Its supported universe is Bitcoin (BTC), Ethereum (ETH), Solana (SOL), XRP, and Dogecoin (DOGE), primarily quoted against USDT for the one-minute scanner. It generates research signals and applies deterministic risk checks; it does not place trades.

## Setup

```bash
python -m pip install -r requirements.txt
export GROQ_API_KEY="your-key"
python trading_agent.py
```

Optional Gmail alerts use `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO`, and `ALERT_EMAIL_PASSWORD` (a Gmail app password).

## Tests

Run the full test suite locally:

```bash
python -m pytest -q
```

The repository includes `pytest.ini` so tests can import the root-level `trading_agent.py` consistently both locally and in GitHub Actions.

## GitHub Actions

The included workflow runs hourly and can also be triggered manually. Add `GROQ_API_KEY` under **Settings → Secrets and variables → Actions**. Add the email secrets only when email alerts are needed.

Workflow path: `.github/workflows/run_agent.yml`.

The workflow:
1. Installs dependencies with pip caching.
2. Runs the test suite before the agent.
3. Runs one market-scan cycle.
4. Commits a changed `trading_agent_log.jsonl` back to the repository.

## Crypto universe

The product scope is crypto-only: BTC, ETH, SOL, XRP, and DOGE. The legacy stock/index helper is not part of the product workflow. The Python snapshot and dashboard are intended to use the configured crypto universe only.

## Signal validation

The LLM is not trusted as the final source of truth. Before a BUY signal can reach the risk layer, Python verifies that:

- The response is a JSON object.
- `action` is either `BUY` or `SKIP`.
- A BUY asset exists in the current market snapshot.
- The BUY entry price is positive, finite, and within 5% of the observed market price.
- The risk calculation uses the configured capital limits.

An invalid model response is discarded rather than converted into a trade candidate.

## Risk controls

- Total capital: INR 3,000
- Per-trade allocation: INR 1,000
- Target: 10% of allocated capital
- Maximum allowed loss: 3% of allocated capital
- Minimum reward:risk ratio: 2.0
- Maximum LLM entry-price deviation: 5%

The LLM proposes a candidate, while the Python risk layer independently calculates quantity, target, stop-loss, and pass/fail.

The total-capital limit is enforced: a requested allocation cannot exceed `TOTAL_CAPITAL_INR`, and the default allocation is capped at total capital.

## Crypto-only scope and limitations

This project is a **market scanner and signal journal**, not a proven trading strategy or execution system.

It currently does **not** provide:
- historical backtesting,
- live order execution,
- broker integration,
- target/stop outcome tracking after a signal,
- a performance dashboard,
- portfolio-level position tracking.

Those should be added only after the signal-generation logic and data quality are validated on historical and paper-trading data.

## Expectations

Logged signals are candidates for your own review, not instructions to trade. No profitability or execution guarantee is made. The agent does not place trades.


## GitHub Pages crypto dashboard

The repository includes a crypto terminal at index.html, designed for GitHub Pages and defaulting to Bitcoin.

The dashboard:
- is crypto-only;
- shows the five configured crypto assets;
- displays the latest hourly agent signal, entry/target/stop levels, rationale and risk/reward;
- keeps up to 168 hourly signal events;
- renders agent-published historical crypto price data with TradingView Lightweight Charts;
- never receives the Groq API key in the browser.

GitHub Pages is deployed by .github/workflows/deploy-pages.yml. In Settings → Pages, select GitHub Actions as the publishing source.

The current agent is still a single-candidate hourly scanner, not a multi-strategy trading engine. The UI exposes the actual modules currently implemented rather than inventing additional strategies.



## Phase 2 — Unattended one-minute scanner

The Phase 2 Cloudflare Worker is in `worker/index.js`, configured by `wrangler.toml`. It scans BTC, ETH, SOL, XRP, and DOGE every minute and can send Telegram alerts on new BUY/SELL signal transitions. It does not execute trades.

Deployment instructions, required Cloudflare KV setup, and Telegram secret configuration are in [docs/phase2-deployment.md](docs/phase2-deployment.md). The Worker must be deployed to your Cloudflare account and configured with your own KV namespace and Telegram bot/chat secrets; it is not active until that setup is completed.
