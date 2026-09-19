# Development Roadmap

## Implemented foundation

- Automated market scan workflow.
- Unit-test configuration and tests.
- AI output validation.
- Deterministic capital/risk calculations.
- JSONL logging path.
- Optional email alerts.
- Explicit no-order-execution boundary.

## Next engineering layers

1. **Signal outcome tracking** — record whether each BUY idea subsequently reached target, stop, or expired.
2. **Historical backtesting** — replay the same decision rules over historical data before making performance claims.
3. **Portfolio accounting** — track open positions, realized/unrealized P&L, exposure, and cash.
4. **Data-quality controls** — timestamps, stale-price detection, retries, rate-limit handling, and source health.
5. **Strategy expansion** — formalize entry/exit rules and test them independently of the LLM.
6. **Observability** — add structured run status, error metrics, and a performance dashboard.
7. **Execution integration** — only as a separate, explicitly controlled layer if broker execution is later required.

The repository should not be treated as a profitable or production trading system until these layers are tested and validated.
