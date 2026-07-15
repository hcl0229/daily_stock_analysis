#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dynamic stock screener by risk profile — runs before main analysis.
Uses efinance (free, no API key) to scan A-share market.
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def fetch_market_snapshot():
    try:
        import efinance as ef
    except ImportError:
        log.error("efinance not installed")
        return None
    log.info("Fetching A-share market snapshot via efinance...")
    try:
        df = ef.stock.get_realtime_quotes()
    except Exception as e:
        log.warning("efinance failed: %s", e)
        return None
    if df is None or df.empty:
        return None
    return df


def screen_by_profile(df, profile):
    import pandas as pd
    if df is None or df.empty:
        return [], ""

    for col in ["涨跌幅", "量比", "换手率", "最新价"]:
        if col not in df.columns:
            return [], ""

    for col in ["涨跌幅", "量比", "换手率", "最新价", "市盈率-动态"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[df["最新价"] > 0].copy()

    pe_col = df.get("市盈率-动态", pd.Series([0] * len(df))).fillna(999)

    if profile == "conservative":
        mask = (
            (pe_col > 0) & (pe_col < 25) &
            (df["涨跌幅"] > -2) & (df["涨跌幅"] < 3) &
            (df["换手率"] > 0.3) & (df["换手率"] < 5) &
            (df["最新价"] > 15)
        )
        top_n, sort_asc, label = 5, False, "Conservative"

    elif profile == "offensive":
        mask = (
            (df["涨跌幅"] > 0.5) & (df["涨跌幅"] < 5) &
            (df["量比"] > 1.2) &
            (df["换手率"] > 2) & (df["换手率"] < 10) &
            (df["最新价"] > 10)
        )
        top_n, sort_asc, label = 5, False, "Offensive"

    elif profile == "aggressive":
        mask = (
            (df["涨跌幅"] > 3) &
            (df["量比"] > 2) &
            (df["换手率"] > 5) &
            (df["最新价"] < 50)
        )
        top_n, sort_asc, label = 4, False, "Aggressive"

    elif profile == "watch":
        mask = (
            (df["涨跌幅"] > -3) & (df["涨跌幅"] < 0) &
            (df["量比"] < 0.8) &
            (df["换手率"] > 1) & (df["换手率"] < 8)
        )
        top_n, sort_asc, label = 4, True, "Watch"

    else:
        return [], ""

    filtered = df[mask].copy()
    if filtered.empty:
        return [], label

    filtered = filtered.sort_values("涨跌幅", ascending=sort_asc).head(top_n)

    codes = []
    for _, row in filtered.iterrows():
        code = str(row.get("股票代码", "")).strip()
        codes.append(code)
        log.info(
            "[%s] %s %s | chg %.2f%% | turn %.2f%% | vol_ratio %.2f",
            label, code, row.get("股票名称", code),
            row["涨跌幅"], row["换手率"], row["量比"]
        )

    return codes, label


def main():
    try:
        import pandas as pd
    except ImportError:
        log.error("pandas not installed")
        sys.exit(1)

    df = fetch_market_snapshot()

    if df is None:
        log.warning("Market data unavailable. Using CSI 300 fallback list.")
        fallback = (
            "600519,000858,300750,002594,601318,000001,"
            "600036,000333,601012,600900,002415,300059,"
            "000002,600276,601166,600030,000651,002475"
        )
        return fallback

    profiles = ["conservative", "offensive", "aggressive", "watch"]
    all_codes = []
    cat_map = {}

    for p in profiles:
        codes, label = screen_by_profile(df, p)
        all_codes.extend(codes)
        cat_map[label] = codes

    if not all_codes:
        log.warning("No matches. Using fallback.")
        return "600519,000858,300750,002594,601318"

    # Print structured output for the workflow to parse
    stock_list = ",".join(all_codes[:18])
    print(f"\nSCREENED:{stock_list}")
    print(f"CONSERVATIVE:{','.join(cat_map.get('Conservative', []))}")
    print(f"OFFENSIVE:{','.join(cat_map.get('Offensive', []))}")
    print(f"AGGRESSIVE:{','.join(cat_map.get('Aggressive', []))}")
    print(f"WATCH:{','.join(cat_map.get('Watch', []))}")
    return stock_list


if __name__ == "__main__":
    result = main()
    if result:
        # GitHub Actions will read this to set STOCK_LIST
        with open("/tmp/screened_stocks.txt", "w") as f:
            f.write(result)
