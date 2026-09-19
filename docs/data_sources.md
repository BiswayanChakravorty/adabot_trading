# Data Sources

## Stocks and indices

Stock/index market data is retrieved with `yfinance`. The current configuration can disable stock scanning with `ENABLE_STOCKS = False`.

## Crypto

Crypto prices are retrieved from CoinGecko's public API. The implementation validates the response shape and rejects non-finite or non-positive prices.

## AI

Groq is used for candidate trade-idea generation. The AI response is parsed as JSON and validated against the market snapshot before risk calculations are performed.

## Alerts

Optional email alerts use SMTP credentials supplied through environment variables.

## Reliability note

These are external data/services. Availability, latency, rate limits, stale data, and API changes can affect a scan. The repository does not currently provide a historical data-quality benchmark.
