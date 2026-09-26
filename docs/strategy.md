# AdaBot Market Strategy

## Supported markets

- **Crypto:** Bitcoin, Ethereum, Solana, XRP, and Dogecoin. One-minute signals use Binance USDT spot pairs.
- **Indian indices:** Nifty 50, Nifty 500, Sensex, and Bank Nifty. Python market snapshots use Yahoo Finance symbols ^NSEI, ^CRSLDX, ^BSESN, and ^NSEBANK. Dashboard index charts use TradingView symbols.

## Crypto signal engine

The Cloudflare Worker calculates EMA 9/21/50, RSI(14), MACD histogram, ATR, relative volume, 20-candle breakout/breakdown, and selected candle patterns from one-minute crypto candles. Scores map to BUY (>=4), SELL (<=-4), or WATCH. These are research signals, not orders.

## Indian index coverage

The dashboard provides TradingView charts for the four indices. The Worker does not yet generate one-minute index signals. Python can include the indices in its market snapshot when data is available; provider coverage and delays may vary.

## Risk and limitations

No historical backtest with fees/slippage or verified live performance statistics is provided. No exchange/broker orders are executed. Treat outputs as research, not financial advice.
