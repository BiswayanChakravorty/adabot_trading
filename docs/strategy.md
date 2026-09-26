# AdaBot Crypto Strategy

## Product scope

AdaBot is a **crypto-only** market scanner. The configured universe is Bitcoin (BTC), Ethereum (ETH), Solana (SOL), XRP, and Dogecoin (DOGE). The one-minute Worker uses Binance public spot-market candles for the USDT pairs. No stocks, indices, forex, or traditional-asset markets are part of the product scope.

## Signal generation

The Cloudflare Worker calculates deterministic indicators from one-minute candles: EMA 9/21/50, RSI(14), MACD histogram, ATR, relative volume, 20-candle breakout/breakdown, and selected candle patterns. The score maps to BUY (>=4), SELL (<=-4), or WATCH. BUY/SELL are analytical signals, not orders; SELL does not mean a short position is opened.

The Python scanner separately uses a crypto market snapshot and may use Groq to propose a candidate. Its output is validated against observed crypto assets and prices before risk calculations.

## Risk and limitations

Signals are not a validated profitable strategy. The project has no exchange execution, historical backtest with fees/slippage, or verified live performance statistics. Crypto trades 24/7 and can be highly volatile; treat all outputs as research signals and independently validate them.
