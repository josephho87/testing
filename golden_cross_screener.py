#!/usr/bin/env python3
"""Golden Cross stock screener.

Screens a universe of US equities for stocks that currently satisfy all
three of the following technical conditions:

  1. Golden cross    - SMA50 has recently crossed above SMA200.
  2. Price-up / volume-up - price closed higher than the prior session on
     volume that is meaningfully above its recent average.
  3. MACD turned positive - the MACD histogram (or the MACD line) has
     recently crossed from negative to positive.

Requires network access to fetch price history (via yfinance). This
sandbox this script was authored in has no outbound network access, so it
has been written and reviewed carefully but *not* executed against live
data here -- run it yourself in an environment with internet access to get
real, current results.

Usage:
    python golden_cross_screener.py
    python golden_cross_screener.py --tickers-file my_tickers.txt
    python golden_cross_screener.py --top 5 --cross-lookback 10 \
        --macd-lookback 5 --volume-multiplier 1.5
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import pandas as pd

DEFAULT_LOOKBACK_DAYS = "2y"  # history window to download per ticker
SMA_SHORT = 50
SMA_LONG = 200
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
VOLUME_AVG_WINDOW = 20

# Small built-in fallback universe used only if we can't fetch the S&P 500
# constituent list (e.g. no network, or Wikipedia's table format changed).
FALLBACK_TICKERS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA", "AVGO",
    "JPM", "V", "UNH", "XOM", "HD", "PG", "MA", "COST", "MRK", "ABBV",
    "PEP", "KO", "ADBE", "CRM", "AMD", "NFLX", "TMO", "LIN", "DIS",
    "WMT", "BAC", "CSCO",
]


@dataclass
class ScreenResult:
    ticker: str
    close: float
    pct_change: float
    volume: float
    rel_volume: float
    sma50: float
    sma200: float
    macd: float
    signal: float
    histogram: float


def get_sp500_tickers() -> list[str]:
    """Fetch current S&P 500 constituents from Wikipedia.

    Falls back to a small hardcoded large-cap list if this fails (no
    network, table layout changed, etc.) so the script still runs.
    """
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        )
        tickers = tables[0]["Symbol"].tolist()
        return [t.replace(".", "-") for t in tickers]
    except Exception as exc:  # noqa: BLE001 - deliberately broad, this is a best-effort fetch
        print(
            f"[warn] could not fetch S&P 500 list from Wikipedia ({exc}); "
            f"falling back to a small built-in ticker list",
            file=sys.stderr,
        )
        return list(FALLBACK_TICKERS)


def load_tickers_from_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return [line.strip().upper() for line in fh if line.strip()]


def compute_macd(close: pd.Series) -> pd.DataFrame:
    ema_fast = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_slow = close.ewm(span=MACD_SLOW, adjust=False).mean()
    macd = ema_fast - ema_slow
    signal = macd.ewm(span=MACD_SIGNAL, adjust=False).mean()
    histogram = macd - signal
    return pd.DataFrame({"macd": macd, "signal": signal, "histogram": histogram})


def check_ticker(
    df: pd.DataFrame,
    cross_lookback: int,
    macd_lookback: int,
    volume_multiplier: float,
) -> ScreenResult | None:
    """Return a ScreenResult if `df` (OHLCV history for one ticker) passes
    all three conditions, otherwise None."""
    if df is None or len(df) < SMA_LONG + cross_lookback + 5:
        return None  # not enough history to evaluate SMA200 reliably

    df = df.copy()
    df["sma50"] = df["Close"].rolling(SMA_SHORT).mean()
    df["sma200"] = df["Close"].rolling(SMA_LONG).mean()
    df["vol_avg"] = df["Volume"].rolling(VOLUME_AVG_WINDOW).mean()

    macd_df = compute_macd(df["Close"])
    df = df.join(macd_df)

    df = df.dropna(subset=["sma50", "sma200", "vol_avg", "histogram"])
    if len(df) < max(cross_lookback, macd_lookback) + 2:
        return None

    today = df.iloc[-1]
    prior_close = df["Close"].iloc[-2]

    # --- 1. Golden cross: SMA50 > SMA200 now, and SMA50 <= SMA200
    #     `cross_lookback` sessions ago (so the cross is recent, not stale).
    if not (today["sma50"] > today["sma200"]):
        return None
    past_idx = -1 - cross_lookback
    if len(df) < abs(past_idx):
        return None
    past = df.iloc[past_idx]
    if not (past["sma50"] <= past["sma200"]):
        return None

    # --- 2. Price up + volume up (價漲量增)
    price_up = today["Close"] > prior_close
    rel_volume = today["Volume"] / today["vol_avg"] if today["vol_avg"] else 0
    volume_up = rel_volume >= volume_multiplier
    if not (price_up and volume_up):
        return None

    # --- 3. MACD histogram turned positive recently
    if not (today["histogram"] > 0):
        return None
    macd_past_idx = -1 - macd_lookback
    if len(df) < abs(macd_past_idx):
        return None
    macd_past = df.iloc[macd_past_idx]
    if not (macd_past["histogram"] <= 0):
        return None

    pct_change = (today["Close"] / prior_close - 1) * 100

    return ScreenResult(
        ticker="",  # filled in by caller
        close=float(today["Close"]),
        pct_change=float(pct_change),
        volume=float(today["Volume"]),
        rel_volume=float(rel_volume),
        sma50=float(today["sma50"]),
        sma200=float(today["sma200"]),
        macd=float(today["macd"]),
        signal=float(today["signal"]),
        histogram=float(today["histogram"]),
    )


def run_screen(
    tickers: list[str],
    cross_lookback: int,
    macd_lookback: int,
    volume_multiplier: float,
    top: int,
) -> list[ScreenResult]:
    import yfinance as yf

    results: list[ScreenResult] = []
    print(f"Downloading history for {len(tickers)} tickers...", file=sys.stderr)

    # Batch download is far faster than one request per ticker.
    data = yf.download(
        tickers,
        period=DEFAULT_LOOKBACK_DAYS,
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    for ticker in tickers:
        try:
            if len(tickers) == 1:
                df = data
            else:
                if ticker not in data.columns.get_level_values(0):
                    continue
                df = data[ticker].dropna(how="all")
        except Exception:
            continue

        try:
            result = check_ticker(df, cross_lookback, macd_lookback, volume_multiplier)
        except Exception as exc:  # noqa: BLE001 - keep scanning other tickers
            print(f"[warn] skipping {ticker}: {exc}", file=sys.stderr)
            continue

        if result is not None:
            result.ticker = ticker
            results.append(result)

    results.sort(key=lambda r: r.rel_volume, reverse=True)
    return results[:top]


def print_results(results: list[ScreenResult]) -> None:
    if not results:
        print("No stocks matched all three conditions today.")
        return

    header = (
        f"{'Ticker':<8}{'Close':>10}{'%Chg':>8}{'Volume':>14}{'RelVol':>8}"
        f"{'SMA50':>10}{'SMA200':>10}{'MACD':>9}{'Signal':>9}{'Hist':>9}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.ticker:<8}{r.close:>10.2f}{r.pct_change:>7.2f}%"
            f"{r.volume:>14,.0f}{r.rel_volume:>7.2f}x"
            f"{r.sma50:>10.2f}{r.sma200:>10.2f}"
            f"{r.macd:>9.3f}{r.signal:>9.3f}{r.histogram:>9.3f}"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers-file",
        help="Path to a text file with one ticker per line. "
        "Defaults to the current S&P 500 constituents.",
    )
    parser.add_argument("--top", type=int, default=5, help="Number of results to show.")
    parser.add_argument(
        "--cross-lookback",
        type=int,
        default=10,
        help="Golden cross must have occurred within this many trading days.",
    )
    parser.add_argument(
        "--macd-lookback",
        type=int,
        default=5,
        help="MACD histogram must have turned positive within this many trading days.",
    )
    parser.add_argument(
        "--volume-multiplier",
        type=float,
        default=1.5,
        help="Today's volume must be at least this many times the 20-day average volume.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    tickers = (
        load_tickers_from_file(args.tickers_file)
        if args.tickers_file
        else get_sp500_tickers()
    )

    results = run_screen(
        tickers=tickers,
        cross_lookback=args.cross_lookback,
        macd_lookback=args.macd_lookback,
        volume_multiplier=args.volume_multiplier,
        top=args.top,
    )
    print_results(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
