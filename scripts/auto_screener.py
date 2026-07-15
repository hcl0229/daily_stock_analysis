#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dynamic stock screener by risk profile.
Primary: tushare (works globally from GitHub US runner)
Fallback: efinance (works from China IP)
Last resort: CSI 300 hardcoded list
"""

import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

FALLBACK_LIST = (
    "600519,000858,300750,002594,601318,000001,"
    "600036,000333,601012,600900,002415,300059,"
    "000002,600276,601166,600030,000651,002475"
)


def fetch_via_tushare():
    """Fetch daily data via tushare API (works globally)."""
    token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        log.info("TUSHARE_TOKEN not set, skipping tushare")
        return None
    try:
        import tushare as ts
    except ImportError:
        log.warning("tushare not installed")
        return None

    pro = ts.pro_api(token)
    log.info("Fetching daily data via tushare...")

    try:
        # Get today's trading data for all A-shares
        df = pro.daily(trade_date="")
        if df is None or df.empty:
            log.warning("tushare daily returned empty")
            return None

        # Get stock basic info for names
        basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,industry")
        if basic is not None and not basic.empty:
            df = df.merge(basic[["ts_code", "name", "industry"]], on="ts_code", how="left")

        # Clean code: 000001.SZ -> 000001
        df["股票代码"] = df["ts_code"].str.split(".").str[0]

        # Rename for compatibility
        df["涨跌幅"] = df["pct_chg"]
        df["最新价"] = df["close"]
        df["换手率"] = df.get("turnover_rate", 0) if "turnover_rate" in df.columns else pd.Series([1]*len(df))
        df["股票名称"] = df.get("name", df["ts_code"])

        # Calculate volume ratio estimate (today's vol / 5-day avg)
        if "vol" in df.columns:
            df["量比"] = 1.0  # Simplified; accurate vol_ratio needs historical compare

        log.info("tushare returned %d rows", len(df))
        return df

    except Exception as e:
        log.warning("tushare failed: %s", e)
        return None


def fetch_via_efinance():
    """Fallback: efinance CDN (may be blocked from US IP)."""
    try:
        import efinance as ef
    except ImportError:
        return None
    log.info("Trying efinance fallback...")
    try:
        df = ef.stock.get_realtime_quotes()
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return None


def screen_by_profile(df, profile):
    """Screen stocks by risk profile."""
    import pandas as pd
    if df is None or df.empty:
        return [], ""

    cols = ["涨跌幅", "最新价"]
    for col in cols:
        if col not in df.columns:
            return [], ""

    for col in cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[df["最新价"] > 0].copy()
    n = len(df)

    # Add synthetic columns if missing (common for tushare)
    if "换手率" not in df.columns:
        df["换手率"] = 1.0
    if "量比" not in df.columns:
        df["量比"] = 1.0
    if "市盈率-动态" in df.columns:
        df["市盈率-动态"] = pd.to_numeric(df["市盈率-动态"], errors="coerce")
    else:
        df["市盈率-动态"] = 20.0

    df["换手率"] = pd.to_numeric(df["换手率"], errors="coerce").fillna(1)
    df["量比"] = pd.to_numeric(df["量比"], errors="coerce").fillna(1)
    df["市盈率-动态"] = df["市盈率-动态"].fillna(20)

    pe = df["市盈率-动态"]
    chg = df["涨跌幅"]
    turnover = df["换手率"]
    price = df["最新价"]
    vratio = df["量比"]

    if profile == "conservative":
        mask = (pe > 0) & (pe < 25) & (chg > -2) & (chg < 3) & (turnover < 5) & (price > 15)
        top_n, asc, label = 5, False, "Conservative"
    elif profile == "offensive":
        mask = (chg > 0.5) & (chg < 5) & (vratio > 1.0) & (turnover > 1) & (price > 10)
        top_n, asc, label = 5, False, "Offensive"
    elif profile == "aggressive":
        mask = (chg > 2) & (vratio > 1.5) & (turnover > 3) & (price < 50)
        top_n, asc, label = 4, False, "Aggressive"
    elif profile == "watch":
        mask = (chg > -3) & (chg < 0) & (vratio < 0.8) & (turnover > 0.5) & (price > 5)
        top_n, asc, label = 4, True, "Watch"
    else:
        return [], ""

    filtered = df[mask].copy()
    if filtered.empty:
        return [], label

    filtered = filtered.sort_values("涨跌幅", ascending=asc).head(top_n)
    codes = []
    for _, row in filtered.iterrows():
        code = str(row.get("股票代码", "")).strip()
        codes.append(code)
        log.info("[%s] %s %s | chg %.2f%% | price %.2f",
                 label, code, row.get("股票名称", ""), row["涨跌幅"], row["最新价"])

    return codes, label


def main():
    try:
        import pandas as pd
    except ImportError:
        log.error("pandas not installed")
        print(f"\nSCREENED:{FALLBACK_LIST}")
        return FALLBACK_LIST

    # Try tushare first (works globally)
    df = fetch_via_tushare()

    # Fall back to efinance (needs China IP)
    if df is None:
        df = fetch_via_efinance()

    if df is None:
        log.warning("All data sources failed. Using CSI 300 fallback.")
        print(f"\nSCREENED:{FALLBACK_LIST}")
        return FALLBACK_LIST

    profiles = ["conservative", "offensive", "aggressive", "watch"]
    all_codes = []
    cat_map = {}

    for p in profiles:
        codes, label = screen_by_profile(df, p)
        all_codes.extend(codes)
        cat_map[label] = codes

    if not all_codes:
        log.warning("No stocks matched. Using fallback.")
        print(f"\nSCREENED:{FALLBACK_LIST}")
        return FALLBACK_LIST

    stock_list = ",".join(all_codes[:18])
    print(f"\nSCREENED:{stock_list}")
    for lbl in ["Conservative", "Offensive", "Aggressive", "Watch"]:
        print(f"{lbl.upper()}:{','.join(cat_map.get(lbl, []))}")
    return stock_list


if __name__ == "__main__":
    result = main()
    if result:
        try:
            with open("/tmp/screened_stocks.txt", "w") as f:
                f.write(result)
        except OSError:
            pass
