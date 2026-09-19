# Architecture

## Runtime flow

1. Load configuration from environment variables and constants.
2. Fetch stock/index data with yfinance when stocks are enabled.
3. Fetch crypto spot prices from CoinGecko.
4. Combine available market observations into a normalized DataFrame.
5. Ask the Groq model for a candidate BUY/SKIP idea using the observed market snapshot.
6. Validate the model output against the current snapshot.
7. Apply deterministic capital, target, stop-loss, and risk/reward controls.
8. Record the cycle as JSONL.
9. Send an email alert only when the signal passes the risk checks.

## Safety boundary

The repository is an analysis/alerting agent. It does not submit broker orders or execute trades.

## Main modules

- `trading_agent.py`: data ingestion, indicators, AI signal generation, validation, risk calculation, logging, and email alerts.
- `tests/test_trading_agent.py`: unit tests for risk and signal-validation behavior.
- `.github/workflows/run_agent.yml`: hourly scheduled/manual CI execution.
