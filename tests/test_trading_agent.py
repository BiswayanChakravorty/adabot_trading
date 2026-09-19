import pandas as pd
import pytest

from trading_agent import (
    MAX_ENTRY_DEVIATION_PCT,
    _rsi,
    calculate_risk_parameters,
    validate_trade_idea,
)


def sample_market():
    return pd.DataFrame(
        [
            {"asset": "Bitcoin", "type": "crypto", "price": 100000.0},
            {"asset": "Ethereum", "type": "crypto", "price": 50000.0},
        ]
    )


def test_risk_parameters():
    risk = calculate_risk_parameters(100.0, 1000.0)
    assert risk["capital_to_invest"] == pytest.approx(1000.0)
    assert risk["quantity"] == pytest.approx(10.0)
    assert risk["target_price"] == pytest.approx(110.0)
    assert risk["stop_loss_price"] == pytest.approx(97.0)
    assert risk["target_profit_inr"] == pytest.approx(100.0)
    assert risk["max_risk_inr"] == pytest.approx(30.0)
    assert risk["risk_reward_ratio"] == pytest.approx(3.33)
    assert risk["passed_risk_check"] is True


def test_default_allocation_never_exceeds_total_capital():
    risk = calculate_risk_parameters(100.0)
    assert risk["capital_to_invest"] <= 3000.0


def test_invalid_entry_price():
    with pytest.raises(ValueError):
        calculate_risk_parameters(0)


def test_capital_above_total_is_rejected():
    with pytest.raises(ValueError):
        calculate_risk_parameters(100.0, 3000.01)


def test_rsi_insufficient_history():
    assert _rsi(pd.Series([1.0, 2.0, 3.0]), period=14) is None


def test_valid_buy_signal_is_normalized():
    idea = validate_trade_idea(
        {
            "asset": "Bitcoin",
            "action": "BUY",
            "entry_price": 101000,
            "rationale": "Momentum remains positive.",
        },
        sample_market(),
    )
    assert idea["asset"] == "Bitcoin"
    assert idea["action"] == "BUY"
    assert idea["entry_price"] == pytest.approx(101000.0)
    assert idea["observed_price"] == pytest.approx(100000.0)


def test_unknown_asset_is_rejected():
    with pytest.raises(ValueError, match="not present"):
        validate_trade_idea(
            {
                "asset": "UnknownCoin",
                "action": "BUY",
                "entry_price": 100000,
            },
            sample_market(),
        )


def test_entry_price_too_far_from_market_is_rejected():
    too_far = 100000 * (1 + MAX_ENTRY_DEVIATION_PCT + 0.01)
    with pytest.raises(ValueError, match="away from observed price"):
        validate_trade_idea(
            {
                "asset": "Bitcoin",
                "action": "BUY",
                "entry_price": too_far,
            },
            sample_market(),
        )


def test_invalid_action_is_rejected():
    with pytest.raises(ValueError, match="action must be BUY or SKIP"):
        validate_trade_idea(
            {
                "asset": "Bitcoin",
                "action": "HOLD",
                "entry_price": 100000,
            },
            sample_market(),
        )


def test_skip_signal_is_safe():
    idea = validate_trade_idea(
        {"asset": None, "action": "SKIP", "entry_price": None},
        sample_market(),
    )
    assert idea["action"] == "SKIP"
    assert idea["entry_price"] is None
