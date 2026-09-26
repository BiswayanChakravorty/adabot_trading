# Phase 2 — Unattended Cloud Scanner + Telegram Alerts

This Worker scans BTC, ETH, SOL, XRP, and DOGE every minute using public Binance 1-minute candles. It computes technical indicators and sends Telegram alerts when a coin transitions into a BUY or SELL state. It does not place orders.

## Architecture
- GitHub Pages: dashboard and chart.
- Cloudflare Worker Cron: unattended one-minute scan.
- Cloudflare KV: stores each coin's last signal state to avoid duplicate alerts.
- Telegram Bot API: sends notifications.

## Deployment

### 1. Create a Telegram bot
1. In Telegram, open @BotFather and run /newbot.
2. Copy the bot token privately; do not commit it or paste it into source code.
3. Open the new bot chat and send /start.
4. Obtain your chat ID using a trusted Telegram API workflow. Keep the bot token secret.

### 2. Create Cloudflare KV
1. Create/sign in to Cloudflare and install Wrangler: npm install -g wrangler.
2. Run wrangler login.
3. Run wrangler kv namespace create SIGNAL_STATE.
4. Copy the returned namespace ID into wrangler.toml, replacing REPLACE_WITH_CLOUDFLARE_KV_NAMESPACE_ID.

### 3. Add secrets and deploy
From the repository root, run:
~~~
wrangler secret put TELEGRAM_BOT_TOKEN
wrangler secret put TELEGRAM_CHAT_ID
wrangler deploy
~~~
Enter each value only in the Wrangler secret prompt. Do not commit secrets or .env files.

The cron trigger is configured for every minute. It may take a short time to activate.

### 4. Verify
Open the deployed Worker URL:
- /health — service health.
- /status — latest scan summary and errors.

In Cloudflare Dashboard, open Workers & Pages → adabot-trading-agent → Logs for scheduled execution logs.

## Signal behavior
- BUY threshold: score >= 4; SELL threshold: score <= -4; otherwise WATCH.
- Sends an alert when a symbol transitions into BUY or SELL, not repeatedly every minute while the same action persists.
- WATCH resets the stored state; a later BUY/SELL transition can alert again.
- If Telegram delivery fails, the scan records an error and can retry on a later scan.
- Target and stop are ATR-derived reference levels, not guaranteed execution prices or proven profitable levels.
- Spot SELL means bearish/exit pressure, not opening a short.

## Limitations
Market-data availability, Cloudflare quotas, Telegram delivery, and network errors can delay or prevent alerts. Check /status and Worker logs. No service guarantees uninterrupted delivery. Backtest and paper-trade signals before risking capital. This Worker does not need exchange trading keys and cannot execute trades.
