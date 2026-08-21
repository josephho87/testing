"""Unit tests for golden_cross_screener.py, using synthetic OHLCV data.

No network access needed -- these exercise the pure screening logic
(SMA golden cross, price/volume, MACD) against hand-built price series.

Run with:
    python -m pytest tests/
or directly:
    python tests/test_golden_cross_screener.py
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from golden_cross_screener import check_ticker, SMA_SHORT, SMA_LONG  # noqa: E402


def _make_uptrend_df(n: int = 300, seed: int = 0) -> pd.DataFrame:
    """A synthetic series that declines then rallies, producing a real
    SMA50/SMA200 golden cross partway through the rally."""
    rng = np.random.default_rng(seed)
    prices = np.concatenate([np.linspace(100, 80, n - 40), np.linspace(80, 130, 40)])
    prices = prices + rng.normal(0, 0.3, n)
    volume = rng.integers(1_000_000, 2_000_000, n).astype(float)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": prices,
            "High": prices * 1.01,
            "Low": prices * 0.99,
            "Close": prices,
            "Volume": volume,
        },
        index=dates,
    )


def _find_first_golden_cross(df: pd.DataFrame) -> int:
    sma50 = df["Close"].rolling(SMA_SHORT).mean()
    sma200 = df["Close"].rolling(SMA_LONG).mean()
    is_cross = sma50 > sma200
    first = is_cross[is_cross & ~is_cross.shift(1).fillna(False)].index[0]
    return df.index.get_loc(first)


def _match_case(volume_multiplier: float = 1.5, cross_lookback: int = 10, macd_lookback: int = 35):
    """A trimmed slice ending shortly after a real golden cross, with a
    price-up + volume-spike day appended as "today"."""
    full = _make_uptrend_df()
    cross_pos = _find_first_golden_cross(full)
    df = full.iloc[: cross_pos + 9].copy()
    df.loc[df.index[-1], "Volume"] = 8_000_000  # volume spike
    df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.02  # price up
    return check_ticker(df, cross_lookback, macd_lookback, volume_multiplier)


def test_matches_when_all_three_conditions_hold():
    result = _match_case()
    assert result is not None
    assert result.rel_volume >= 1.5
    assert result.sma50 > result.sma200
    assert result.histogram > 0


def test_rejects_declining_series():
    n = 300
    rng = np.random.default_rng(0)
    prices = np.linspace(100, 90, n) + rng.normal(0, 0.3, n)
    volume = rng.integers(1_000_000, 2_000_000, n).astype(float)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame(
        {"Open": prices, "High": prices * 1.01, "Low": prices * 0.99,
         "Close": prices, "Volume": volume},
        index=dates,
    )
    assert check_ticker(df, 10, 35, 1.5) is None


def test_rejects_when_no_volume_spike():
    full = _make_uptrend_df()
    cross_pos = _find_first_golden_cross(full)
    df = full.iloc[: cross_pos + 9].copy()
    df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 1.02  # price up
    # volume left at its normal (non-spiking) level
    assert check_ticker(df, 10, 35, 1.5) is None


def test_rejects_when_price_falls_today():
    full = _make_uptrend_df()
    cross_pos = _find_first_golden_cross(full)
    df = full.iloc[: cross_pos + 9].copy()
    df.loc[df.index[-1], "Volume"] = 8_000_000
    df.loc[df.index[-1], "Close"] = df["Close"].iloc[-2] * 0.98  # price down
    assert check_ticker(df, 10, 35, 1.5) is None


def test_rejects_when_macd_flip_too_stale():
    # A small macd_lookback should reject a flip that happened long before "today".
    assert _match_case(macd_lookback=5) is None


def test_rejects_when_not_enough_history():
    df = _make_uptrend_df(n=100)  # shorter than SMA_LONG + lookback + buffer
    assert check_ticker(df, 10, 5, 1.5) is None


def _run_all():
    tests = [obj for name, obj in globals().items() if name.startswith("test_")]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return failures


if __name__ == "__main__":
    raise SystemExit(1 if _run_all() else 0)
