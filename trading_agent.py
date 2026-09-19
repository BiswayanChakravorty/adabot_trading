"""
trading_agent.py

A free-to-run market-scanning agent that:
  1. Pulls stock/index data (yfinance) and crypto data (CoinGecko).
  2. Sends a market snapshot to Groq for a candidate trade idea.
  3. Applies a deterministic percentage-based risk-management filter.
  4. Logs results to JSONL and optionally emails passed candidates.
  5. Runs locally or on GitHub Actions.

It does not place trades.
"""

import datetime
import json
import os
import smtplib
from email.mime.text import MIMEText

import pandas as pd
import requests
import yfinance as yf
from groq import Groq

ENABLE_STOCKS = False

STOCK_WATCHLIST = {
    "Sensex": "^BSESN",
    "Nifty 50": "^NSEI",
    "Bank Nifty": "^NSEBANK",
    "Nifty IT": "^CNXIT",
}

CRYPTO_WATCHLIST = {
    "Bitcoin": "bitcoin",
    "Ethereum": "ethereum",
    "Solana": "solana",
    "XRP": "ripple",
    "Dogecoin": "dogecoin",
}

TOTAL_CAPITAL_INR = 3000.0
PER_TRADE_ALLOCATION_INR = 1000.0
TARGET_PROFIT_PCT = 0.10
MAX_RISK_PCT = 0.03
MIN_RISK_REWARD_RATIO = 2.0

LOG_FILE = "trading_agent_log.jsonl"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
ALERT_EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD", "")


def fetch_stock_data() -> pd.DataFrame:
    rows = []
    for name, ticker in STOCK_WATCHLIST.items():
        try:
            hist = yf.Ticker(ticker).history(period="1mo", interval="1d")
            if hist.empty:
                continue
            last_close = float(hist["Close"].iloc[-1])
            month_ago = float(hist["Close"].iloc[0])
            change_pct = (last_close - month_ago) / month_ago * 100
            rsi = _rsi(hist["Close"])
            rows.append({
                "asset": name,
                "type": "stock",
                "price": round(last_close, 2),
                "1mo_change_pct": round(change_pct, 2),
                "rsi_14": round(rsi, 1) if rsi is not None else None,
            })
        except Exception as exc:
            print(f"[warn] failed to fetch {name} ({ticker}): {exc}")
    return pd.DataFrame(rows)


def fetch_crypto_data() -> pd.DataFrame:
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "inr",
        "ids": ",".join(CRYPTO_WATCHLIST.values()),
        "price_change_percentage": "24h,30d",
    }
    rows = []
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        id_to_name = {value: key for key, value in CRYPTO_WATCHLIST.items()}
        for coin in response.json():
            rows.append({
                "asset": id_to_name.get(coin["id"], coin["id"]),
                "type": "crypto",
                "price": coin.get("current_price"),
                "24h_change_pct": round(
                    coin.get("price_change_percentage_24h") or 0, 2
                ),
                "30d_change_pct": round(
                    coin.get("price_change_percentage_30d_in_currency") or 0, 2
                ),
            })
    except Exception as exc:
        print(f"[warn] failed to fetch crypto data: {exc}")
    return pd.DataFrame(rows)


def _rsi(closes: pd.Series, period: int = 14):
    if len(closes) < period + 1:
        return None
    delta = closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    last_gain, last_loss = gain.iloc[-1], loss.iloc[-1]
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return 100 - (100 / (1 + rs))


def get_trade_idea(market_df: pd.DataFrame) -> dict | None:
    if not GROQ_API_KEY:
        print("[warn] GROQ_API_KEY not set - logging raw data only.")
        return None

    client = Groq(api_key=GROQ_API_KEY)
    market_summary = market_df.to_string(index=False)
    prompt = f"""You are a cautious market-scanning assistant.

Today's market snapshot:
{market_summary}

Capital available for this check: INR {PER_TRADE_ALLOCATION_INR}.

From this list ONLY, identify at most one asset with a favorable short-term
risk/reward setup using trend and momentum. If none looks reasonable, choose SKIP.

Respond with ONLY JSON:
{{
  "asset": "<name from list, or null>",
  "action": "BUY" or "SKIP",
  "entry_price": <number or null>,
  "rationale": "<one sentence>"
}}
"""
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        content = (response.choices[0].message.content or "").strip()
        return json.loads(content)
    except Exception as exc:
        print(f"[warn] Groq analysis failed: {exc}")
        return None


def calculate_risk_parameters(
    entry_price: float,
    capital_to_invest: float = PER_TRADE_ALLOCATION_INR,
) -> dict:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    if capital_to_invest <= 0:
        raise ValueError("capital_to_invest must be positive")

    quantity = capital_to_invest / entry_price
    target_profit_inr = capital_to_invest * TARGET_PROFIT_PCT
    max_allowed_loss_inr = capital_to_invest * MAX_RISK_PCT

    target_price = entry_price + (target_profit_inr / quantity)
    stop_loss_price = entry_price - (max_allowed_loss_inr / quantity)
    potential_reward = target_price - entry_price
    potential_risk = entry_price - stop_loss_price
    rrr = potential_reward / potential_risk if potential_risk > 0 else 0.0

    return {
        "quantity": round(quantity, 6),
        "target_price": round(target_price, 2),
        "stop_loss_price": round(stop_loss_price, 2),
        "target_profit_inr": round(target_profit_inr, 2),
        "max_risk_inr": round(max_allowed_loss_inr, 2),
        "risk_reward_ratio": round(rrr, 2),
        "passed_risk_check": rrr >= MIN_RISK_REWARD_RATIO,
    }


def log_result(record: dict):
    record = dict(record)
    record["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    print(json.dumps(record, indent=2))


def send_email_alert(subject: str, body: str):
    if not (ALERT_EMAIL_FROM and ALERT_EMAIL_TO and ALERT_EMAIL_PASSWORD):
        return

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = ALERT_EMAIL_FROM
    message["To"] = ALERT_EMAIL_TO

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(ALERT_EMAIL_FROM, ALERT_EMAIL_PASSWORD)
            server.send_message(message)
    except Exception as exc:
        print(f"[warn] email alert failed: {exc}")


def run_agent_cycle():
    print(
        f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] "
        "Running market scan..."
    )

    crypto_df = fetch_crypto_data()
    if ENABLE_STOCKS:
        stock_df = fetch_stock_data()
        market_df = pd.concat(
            [stock_df, crypto_df], ignore_index=True, sort=False
        )
    else:
        market_df = crypto_df

    if market_df.empty:
        log_result({"status": "error", "message": "No market data retrieved."})
        return

    idea = get_trade_idea(market_df)

    if not idea or idea.get("action") != "BUY" or not idea.get("entry_price"):
        log_result({
            "status": "no_trade",
            "market_snapshot": market_df.to_dict(orient="records"),
            "ai_response": idea,
        })
        return

    try:
        entry_price = float(idea["entry_price"])
        risk = calculate_risk_parameters(entry_price)
    except (TypeError, ValueError) as exc:
        log_result({
            "status": "invalid_ai_signal",
            "market_snapshot": market_df.to_dict(orient="records"),
            "ai_response": idea,
            "message": str(exc),
        })
        return

    record = {
        "status": (
            "signal_passed"
            if risk["passed_risk_check"]
            else "signal_rejected_by_risk_filter"
        ),
        "asset": idea.get("asset"),
        "action": idea.get("action"),
        "entry_price": entry_price,
        "rationale": idea.get("rationale"),
        **risk,
    }
    log_result(record)

    if risk["passed_risk_check"]:
        body = (
            f"Asset: {record['asset']}\n"
            f"Entry: INR {record['entry_price']}\n"
            f"Target: INR {record['target_price']}\n"
            f"Stop-loss: INR {record['stop_loss_price']}\n"
            f"Risk:Reward = 1:{record['risk_reward_ratio']}\n\n"
            f"Rationale: {record['rationale']}\n\n"
            "This is a candidate to review yourself, not an instruction to trade."
        )
        send_email_alert(f"Trade candidate: {record['asset']}", body)
    else:
        print("Signal rejected by risk filter; no alert sent.")


if __name__ == "__main__":
    run_agent_cycle()
