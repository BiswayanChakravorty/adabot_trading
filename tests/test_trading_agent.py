import pandas as pd
import pytest

from trading_agent import calculate_risk_parameters, _rsi


def test_risk_parameters():
    risk = calculate_risk_parameters(100.0, 1000.0)
    assert risk["quantity"] == pytest.approx(10.0)
    assert risk["target_price"] == pytest.approx(110.0)
    assert risk["stop_loss_price"] == pytest.approx(97.0)
    assert risk["target_profit_inr"] == pytest.approx(100.0)
    assert risk["max_risk_inr"] == pytest.approx(30.0)
    assert risk["passed_risk_check"] is True


def test_invalid_entry_price():
    with pytest.raises(ValueError):
        calculate_risk_parameters(0)


def test_rsi_insufficient_history():
    assert _rsi(pd.Series([1.0, 2.0, 3.0]), period=14) is None
