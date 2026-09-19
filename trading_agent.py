"""
trading_agent.py

A free-to-run market-scanning agent that:
  1. Pulls stock/index data (yfinance) and crypto data (CoinGecko).
  2. Sends a market snapshot to Groq for a candidate trade idea.
  3. Validates the model output against the live market snapshot.
  4. Applies a deterministic capital/risk-management filter.
  5. Logs results to JSONL and optionally emails passed candidates.
  6. Runs locally or on GitHub Actions.

It does not place trades.
"""

import datetime
import json
import math
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

# Prevent the LLM from inventing an entry price far away from the observed market.
MAX_ENTRY_DEVIATION_PCT = 0.05

LOG_FILE = "trading_agent_log.jsonl"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = "openai/gpt-oss-120b"
ALERT_EMAIL_FROM = os.getenv("ALERT_EMAIL_FROM", "")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
ALERT_EMAIL_PASSWORD = os.getenv("ALERT_EMAIL_PASSWORD", "")


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _finite_float(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be numeric") from None
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


def _positive_float(value: object, field_name: str) -> float:
    number = _finite_float(value, field_name)
    if number <= 0:
        raise ValueError(f"{field_name} must be positive")
    return number


def fetch_stock_data() -> pd.DataFrame:
    rows = []
    for name, ticker in STOCK_WATCHLIST.items():
        try:
            hist = yf.Ticker(ticker).history(period="1mo", interval="1d")
            if hist.empty:
                continue

            if "Close" not in hist.columns:
                continue
            last_close = _positive_float(hist["Close"].iloc[-1], f"{name} close")
            month_ago = _positive_float(hist["Close"].iloc[0], f"{name} month-ago close")

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
        response = requests.get(
            url,
            params=params,
            timeout=15,
            headers={"User-Agent": "adabot-trading/1.0"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("CoinGecko response was not a list")

        id_to_name = {value: key for key, value in CRYPTO_WATCHLIST.items()}
        for coin in payload:
            coin_id = coin.get("id")
            price = coin.get("current_price")
            if not coin_id or price is None:
                continue
            try:
                price = _positive_float(price, f"{coin_id} current price")
                change_24h = _finite_float(
                    coin.get("price_change_percentage_24h") or 0,
                    f"{coin_id} 24h change",
                )
                change_30d = _finite_float(
                    coin.get("price_change_percentage_30d_in_currency") or 0,
                    f"{coin_id} 30d change",
                )
            except ValueError:
                continue

            rows.append({
                "asset": id_to_name.get(coin_id, coin_id),
                "type": "crypto",
                "price": price,
                "24h_change_pct": round(change_24h, 2),
                "30d_change_pct": round(change_30d, 2),
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


def validate_trade_idea(idea: object, market_df: pd.DataFrame) -> dict:
    """Validate and normalize an LLM trade idea before risk calculations."""
    if not isinstance(idea, dict):
        raise ValueError("AI response must be a JSON object")
    if not isinstance(market_df, pd.DataFrame):
        raise ValueError("market snapshot must be a pandas DataFrame")

    action = str(idea.get("action", "")).strip().upper()
    if action not in {"BUY", "SKIP"}:
        raise ValueError("action must be BUY or SKIP")

    if action == "SKIP":
        return {
            "asset": None,
            "action": "SKIP",
            "entry_price": None,
            "rationale": str(idea.get("rationale", "")).strip(),
        }

    if market_df.empty or "asset" not in market_df.columns or "price" not in market_df.columns:
        raise ValueError("market snapshot has no usable asset/price columns")

    asset = str(idea.get("asset", "")).strip()
    if not asset:
        raise ValueError("BUY signal must contain an asset")

    matches = market_df[market_df["asset"].astype(str) == asset]
    if matches.empty:
        raise ValueError(f"AI asset '{asset}' is not present in the market snapshot")

    entry_price = _positive_float(idea.get("entry_price"), "BUY signal entry_price")
    current_price = _positive_float(
        matches.iloc[0]["price"], f"market price for '{asset}'"
    )

    deviation = abs(entry_price - current_price) / current_price
    if deviation > MAX_ENTRY_DEVIATION_PCT:
        raise ValueError(
            f"entry_price is {deviation:.2%} away from observed price; "
            f"maximum allowed is {MAX_ENTRY_DEVIATION_PCT:.2%}"
        )

    return {
        "asset": asset,
        "action": "BUY",
        "entry_price": entry_price,
        "rationale": str(idea.get("rationale", "")).strip(),
        "observed_price": current_price,
        "entry_deviation_pct": round(deviation * 100, 4),
    }


def get_trade_idea(market_df: pd.DataFrame) -> dict | None:
    if not GROQ_API_KEY:
        print("[warn] GROQ_API_KEY not set - logging raw data only.")
        return None

    client = Groq(api_key=GROQ_API_KEY)
    market_summary = market_df.to_string(index=False)
    capital_for_trade = min(PER_TRADE_ALLOCATION_INR, TOTAL_CAPITAL_INR)
    prompt = f"""You are a cautious market-scanning assistant.

Today's market snapshot:
{market_summary}

Maximum capital allocation for this check: INR {capital_for_trade}.

From this list ONLY, identify at most one asset with a favorable short-term
risk/reward setup using the supplied trend and momentum data. Do not invent
assets or prices. If none looks reasonable, choose SKIP.

For BUY, entry_price must be close to the supplied current price for that asset.

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
            response_format={"type": "json_schema", "json_schema": {"name": "trade_idea", "strict": true, "schema": {"type": "object", "properties": {"asset": {"type": ["string", "null"]}, "action": {"type": "string", "enum": ["BUY", "SKIP"]}, "entry_price": {"type": ["number", "null"]}, "rationale": {"type": "string"}}, "required": ["asset", "action", "entry_price", "rationale"], "additionalProperties": false}}},
        )
        content = (response.choices[0].message.content or "").strip()
        return validate_trade_idea(json.loads(content), market_df)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[warn] invalid Groq trade idea: {exc}")
        return None
    except Exception as exc:
        print(f"[warn] Groq analysis failed: {exc}")
        return None


def calculate_risk_parameters(
    entry_price: float,
    capital_to_invest: float | None = None,
) -> dict:
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")

    if TOTAL_CAPITAL_INR <= 0:
        raise ValueError("TOTAL_CAPITAL_INR must be positive")
    if PER_TRADE_ALLOCATION_INR <= 0:
        raise ValueError("PER_TRADE_ALLOCATION_INR must be positive")
    if PER_TRADE_ALLOCATION_INR > TOTAL_CAPITAL_INR:
        raise ValueError("PER_TRADE_ALLOCATION_INR cannot exceed TOTAL_CAPITAL_INR")

    if capital_to_invest is None:
        capital_to_invest = min(PER_TRADE_ALLOCATION_INR, TOTAL_CAPITAL_INR)
    if capital_to_invest <= 0:
        raise ValueError("capital_to_invest must be positive")
    if capital_to_invest > TOTAL_CAPITAL_INR:
        raise ValueError("capital_to_invest cannot exceed TOTAL_CAPITAL_INR")

    quantity = capital_to_invest / entry_price
    target_profit_inr = capital_to_invest * TARGET_PROFIT_PCT
    max_allowed_loss_inr = capital_to_invest * MAX_RISK_PCT

    target_price = entry_price + (target_profit_inr / quantity)
    stop_loss_price = entry_price - (max_allowed_loss_inr / quantity)
    potential_reward = target_price - entry_price
    potential_risk = entry_price - stop_loss_price
    rrr = potential_reward / potential_risk if potential_risk > 0 else 0.0

    return {
        "capital_to_invest": round(capital_to_invest, 2),
        "quantity": round(quantity, 6),
        "target_price": round(target_price, 2),
        "stop_loss_price": round(stop_loss_price, 2),
        "target_profit_inr": round(target_profit_inr, 2),
        "max_risk_inr": round(max_allowed_loss_inr, 2),
        "risk_reward_ratio": rrr,
        "passed_risk_check": rrr >= MIN_RISK_REWARD_RATIO,
    }


def log_result(record: dict):
    record = dict(record)
    record["timestamp"] = _utc_now()
    with open(LOG_FILE, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps(record, indent=2, ensure_ascii=False))


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
    print(f"[{_utc_now()}] Running market scan...")

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

    raw_idea = get_trade_idea(market_df)

    if not raw_idea or raw_idea.get("action") != "BUY" or not raw_idea.get("entry_price"):
        log_result({
            "status": "no_trade",
            "market_snapshot": market_df.to_dict(orient="records"),
            "ai_response": raw_idea,
        })
        return

    try:
        # get_trade_idea already validates, but revalidate here so this boundary
        # remains safe if the function is changed or mocked later.
        idea = validate_trade_idea(raw_idea, market_df)
        risk = calculate_risk_parameters(idea["entry_price"])
    except (TypeError, ValueError) as exc:
        log_result({
            "status": "invalid_ai_signal",
            "market_snapshot": market_df.to_dict(orient="records"),
            "ai_response": raw_idea,
            "message": str(exc),
        })
        return

    record = {
        "status": (
            "signal_passed"
            if risk["passed_risk_check"]
            else "signal_rejected_by_risk_filter"
        ),
        "asset": idea["asset"],
        "action": idea["action"],
        "entry_price": idea["entry_price"],
        "observed_price": idea.get("observed_price"),
        "entry_deviation_pct": idea.get("entry_deviation_pct"),
        "rationale": idea.get("rationale"),
        **risk,
    }
    log_result(record)

    if risk["passed_risk_check"]:
        body = (
            f"Asset: {record['asset']}\n"
            f"Entry: INR {record['entry_price']}\n"
            f"Observed: INR {record['observed_price']}\n"
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
