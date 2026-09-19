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
DASHBOARD_FILE = "dashboard_data.json"

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



def fetch_crypto_chart_data() -> dict:
    """Fetch public historical price series for the dashboard without exposing credentials."""
    charts = {}
    for name, coin_id in CRYPTO_WATCHLIST.items():
        try:
            response = requests.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
                params={"vs_currency": "usd", "days": "30"},
                timeout=20,
                headers={"User-Agent": "adabot-trading/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
            prices = payload.get("prices", [])
            clean = []
            for point in prices:
                if not isinstance(point, list) or len(point) < 2:
                    continue
                try:
                    timestamp = int(float(point[0]) / 1000)
                    price = _positive_float(point[1], f"{name} chart price")
                except (TypeError, ValueError):
                    continue
                clean.append({"time": timestamp, "value": price})
            if clean:
                charts[name] = clean[-1000:]
        except Exception as exc:
            print(f"[warn] failed to fetch chart data for {name}: {exc}")
    return charts


def _rsi(closes: pd.Series, period: int = 14):
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError("period must be a positive integer")
    if not isinstance(closes, pd.Series):
        closes = pd.Series(closes)
    if len(closes) < period + 1:
        return None

    numeric_closes = pd.to_numeric(closes, errors="coerce")
    if numeric_closes.isna().any():
        return None

    delta = numeric_closes.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    last_gain, last_loss = gain.iloc[-1], loss.iloc[-1]
    if last_loss == 0:
        return 50.0 if last_gain == 0 else 100.0
    if last_gain == 0:
        return 0.0
    rs = last_gain / last_loss
    return 100 - (100 / (1 + rs))



def fetch_strategy_data() -> dict:
    """Fetch 30-day price data for the configured crypto universe."""
    result = {}
    for name, coin_id in CRYPTO_WATCHLIST.items():
        try:
            response = requests.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
                params={"vs_currency": "usd", "days": "30", "interval": "daily"},
                timeout=20,
                headers={"User-Agent": "adabot-trading/1.0"},
            )
            response.raise_for_status()
            prices = response.json().get("prices", [])
            rows = []
            for point in prices:
                if not isinstance(point, list) or len(point) < 2:
                    continue
                try:
                    rows.append({"timestamp": int(float(point[0]) / 1000), "close": _positive_float(point[1], f"{name} strategy price")})
                except (TypeError, ValueError):
                    continue
            if rows:
                result[name] = rows
        except Exception as exc:
            print(f"[warn] strategy data failed for {name}: {exc}")
    return result


def _strategy_indicators(closes: pd.Series) -> dict:
    values = pd.to_numeric(closes, errors="coerce").dropna()
    if len(values) < 20:
        return {}
    ema21 = values.ewm(span=21, adjust=False).mean()
    ema50 = values.ewm(span=50, adjust=False).mean()
    macd = values.ewm(span=12, adjust=False).mean() - values.ewm(span=26, adjust=False).mean()
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    rsi = _rsi(values, 14)
    recent_high = values.iloc[-21:-1].max() if len(values) >= 21 else values.max()
    return {"price": float(values.iloc[-1]), "ema21": float(ema21.iloc[-1]), "ema50": float(ema50.iloc[-1]), "macd": float(macd.iloc[-1]), "macd_signal": float(macd_signal.iloc[-1]), "rsi": float(rsi) if rsi is not None else None, "recent_high": float(recent_high)}


def evaluate_strategies(strategy_data: dict) -> dict:
    output = {}
    for asset, rows in strategy_data.items():
        ind = _strategy_indicators(pd.Series([x["close"] for x in rows]))
        if not ind:
            continue
        rsi = ind["rsi"]
        strategies = {
            "trend": "BUY" if ind["price"] > ind["ema21"] > ind["ema50"] else "WAIT",
            "momentum": "BUY" if rsi is not None and 52 <= rsi <= 68 else "WAIT",
            "macd": "BUY" if ind["macd"] > ind["macd_signal"] and ind["macd"] > 0 else "WAIT",
            "breakout": "BUY" if ind["price"] > ind["recent_high"] else "WAIT",
            "mean_reversion": "BUY" if rsi is not None and rsi < 35 else "WAIT",
        }
        votes = sum(v == "BUY" for v in strategies.values())
        output[asset] = {"consensus": "BUY" if votes >= 3 else "WAIT", "buy_votes": votes, "total_strategies": len(strategies), "strategies": strategies, "indicators": ind}
    return output


def build_strategy_summary(strategy_data: dict) -> dict:
    evaluations = evaluate_strategies(strategy_data)
    candidates = [{"asset": a, "buy_votes": d["buy_votes"], "total_strategies": d["total_strategies"]} for a, d in evaluations.items() if d["consensus"] == "BUY"]
    candidates.sort(key=lambda x: x["buy_votes"], reverse=True)
    return {"strategy_count": 5, "strategy_names": ["Trend", "Momentum", "MACD", "Breakout", "Mean Reversion"], "evaluations": evaluations, "candidates": candidates}



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
    strategy_context = getattr(get_trade_idea, "_strategy_context", {})
    capital_for_trade = min(PER_TRADE_ALLOCATION_INR, TOTAL_CAPITAL_INR)
    prompt = f"""You are a cautious market-scanning assistant.

Today's market snapshot:
{market_summary}

Maximum capital allocation for this check: INR {capital_for_trade}.

From this list ONLY, identify at most one asset with a favorable short-term
risk/reward setup using the supplied market data.
Strategy context:
{strategy_context} Do not invent
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
            response_format={"type": "json_schema", "json_schema": {"name": "trade_idea", "strict": True, "schema": {"type": "object", "properties": {"asset": {"type": ["string", "null"]}, "action": {"type": "string", "enum": ["BUY", "SKIP"]}, "entry_price": {"type": ["number", "null"]}, "rationale": {"type": "string"}}, "required": ["asset", "action", "entry_price", "rationale"], "additionalProperties": false}}},
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
    entry_price = _positive_float(entry_price, "entry_price")

    total_capital = _positive_float(TOTAL_CAPITAL_INR, "TOTAL_CAPITAL_INR")
    per_trade = _positive_float(
        PER_TRADE_ALLOCATION_INR, "PER_TRADE_ALLOCATION_INR"
    )
    target_pct = _positive_float(TARGET_PROFIT_PCT, "TARGET_PROFIT_PCT")
    max_risk_pct = _positive_float(MAX_RISK_PCT, "MAX_RISK_PCT")
    min_rrr = _finite_float(MIN_RISK_REWARD_RATIO, "MIN_RISK_REWARD_RATIO")
    if max_risk_pct >= 1:
        raise ValueError("MAX_RISK_PCT must be less than 1")
    if min_rrr < 0:
        raise ValueError("MIN_RISK_REWARD_RATIO cannot be negative")
    if per_trade > total_capital:
        raise ValueError("PER_TRADE_ALLOCATION_INR cannot exceed TOTAL_CAPITAL_INR")

    if capital_to_invest is None:
        capital_to_invest = min(per_trade, total_capital)
    else:
        capital_to_invest = _positive_float(
            capital_to_invest, "capital_to_invest"
        )

    if capital_to_invest > total_capital:
        raise ValueError("capital_to_invest cannot exceed TOTAL_CAPITAL_INR")

    quantity = capital_to_invest / entry_price
    target_profit_inr = capital_to_invest * target_pct
    max_allowed_loss_inr = capital_to_invest * max_risk_pct

    target_price = entry_price * (1 + target_pct)
    stop_loss_price = entry_price * (1 - max_risk_pct)
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
        "passed_risk_check": rrr >= min_rrr,
    }



def publish_dashboard_data(
    market_df: pd.DataFrame,
    signal: dict | None = None,
    risk: dict | None = None,
    status: str = "no_trade",
    chart_data: dict | None = None,
    strategy_summary: dict | None = None,
):
    """Publish sanitized, frontend-ready state. No API keys or credentials are written."""
    history = []
    if os.path.exists(DASHBOARD_FILE):
        try:
            with open(DASHBOARD_FILE, "r", encoding="utf-8") as handle:
                previous = json.load(handle)
            history = previous.get("history", [])
            if not isinstance(history, list):
                history = []
        except (OSError, json.JSONDecodeError):
            history = []

    event = {
        "timestamp": _utc_now(),
        "status": status,
        "asset": signal.get("asset") if signal else None,
        "action": signal.get("action") if signal else "SKIP",
        "entry_price": signal.get("entry_price") if signal else None,
        "observed_price": signal.get("observed_price") if signal else None,
        "target_price": risk.get("target_price") if risk else None,
        "stop_loss_price": risk.get("stop_loss_price") if risk else None,
        "risk_reward_ratio": risk.get("risk_reward_ratio") if risk else None,
        "rationale": signal.get("rationale") if signal else "",
    }
    history.append(event)
    history = history[-168:]

    payload = {
        "generated_at": event["timestamp"],
        "refresh_interval_minutes": 60,
        "default_asset": "Bitcoin",
        "agent": {
            "name": "AdaBot Trading Agent",
            "mode": "crypto-only",
            "schedule": "hourly",
            "execution": "signal-only",
            "strategy": "AI short-term scanner + deterministic risk filter",
        },
        "market_snapshot": market_df.to_dict(orient="records"),
        "chart_history": chart_data or {},
        "strategy_summary": strategy_summary or {},
        "latest_signal": event,
        "history": history,
        "modules": [
            {
                "id": "ai-scanner",
                "name": "AI Short-Term Scanner",
                "description": "Scores the supplied crypto snapshot and proposes at most one BUY or SKIP candidate.",
                "state": "active",
            },
            {
                "id": "risk-filter",
                "name": "Deterministic Risk Filter",
                "description": "Calculates allocation, target, stop-loss and reward:risk independently of the model.",
                "state": "active",
            },
            {
                "id": "market-context",
                "name": "Market Context",
                "description": "Publishes observed crypto prices and 24h/30d movement used by the agent.",
                "state": "active",
            },
        ],
        "risk_config": {
            "total_capital_inr": TOTAL_CAPITAL_INR,
            "per_trade_allocation_inr": PER_TRADE_ALLOCATION_INR,
            "target_profit_pct": TARGET_PROFIT_PCT,
            "max_risk_pct": MAX_RISK_PCT,
            "minimum_risk_reward_ratio": MIN_RISK_REWARD_RATIO,
            "max_entry_deviation_pct": MAX_ENTRY_DEVIATION_PCT,
        },
    }
    with open(DASHBOARD_FILE, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\\n")


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
    chart_data = fetch_crypto_chart_data()
    strategy_summary = build_strategy_summary(fetch_strategy_data())
    get_trade_idea._strategy_context = strategy_summary
    if ENABLE_STOCKS:
        stock_df = fetch_stock_data()
        market_df = pd.concat(
            [stock_df, crypto_df], ignore_index=True, sort=False
        )
    else:
        market_df = crypto_df

    if market_df.empty:
        publish_dashboard_data(market_df, status="error", chart_data=chart_data, strategy_summary=strategy_summary)
        log_result({"status": "error", "message": "No market data retrieved."})
        return

    raw_idea = get_trade_idea(market_df)

    if (
        not raw_idea
        or raw_idea.get("action") != "BUY"
        or raw_idea.get("entry_price") is None
    ):
        publish_dashboard_data(market_df, signal=raw_idea, status="no_trade", chart_data=chart_data)
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
        publish_dashboard_data(market_df, signal=raw_idea, status="invalid_ai_signal", chart_data=chart_data)
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
    publish_dashboard_data(
        market_df,
        signal=idea,
        risk=risk,
        status=record["status"],
        chart_data=chart_data,
        strategy_summary=strategy_summary,
    )
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
