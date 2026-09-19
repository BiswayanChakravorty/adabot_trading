# Strategy

The current implementation is a lightweight market-scanning strategy rather than a fully backtested trading system.

## Market universe

The code defines a stock/index watchlist and a crypto watchlist. Stock scanning is currently controlled by `ENABLE_STOCKS`; crypto scanning uses CoinGecko.

## Signal generation

Groq is used to generate a candidate trade idea from the market snapshot. The model is instructed to return structured JSON and may return BUY or SKIP.

The AI output is not treated as trusted execution data. BUY signals are checked against the assets and prices actually observed by the agent.

## Indicators

The current code includes an RSI helper. The repository does not currently implement a complete, historically validated multi-indicator strategy.

## Current limitation

There is no historical backtesting or measured strategy performance in the repository. Therefore no profitability claim should be inferred from the presence of the AI signal layer.
