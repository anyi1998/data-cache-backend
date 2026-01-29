#!/usr/bin/env python3
"""
技术分析预计算脚本
每10分钟运行，计算热门 ETF 的完整分析数据
"""
import os
import sys
import json
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 在导入 akshare 之前应用代理补丁
from app.utils.proxy_patch import apply_proxy_patch
apply_proxy_patch()

import akshare as ak
import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

# 配置请求头，减少反爬虫概率
CUSTOM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 尝试配置 akshare 的请求头（如果支持）
try:
    if hasattr(ak, 'headers'):
        ak.headers = CUSTOM_HEADERS
except:
    pass

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# 热门 ETF 列表（预计算这些）
HOT_ETFS = [
    "510300", "510500", "510050", "159915", "159919",  # 宽基
    "512480", "512400", "512010", "512660", "512760",  # 科技
    "510170", "159985", "518880", "513050", "513100",  # 消费/黄金/纳指
    "512690", "159766", "159992", "512800", "512880",  # 白酒/芯片/银行
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_etf_history(symbol: str, days: int = 120):
    """获取 ETF 历史 K 线 - 使用 akshare"""
    try:
        # 使用 akshare 替代 efinance (更稳定)
        df = ak.fund_etf_hist_em(symbol=symbol, period="daily", adjust="qfq")
        if df is None or df.empty:
            return None
        
        rename_map = {
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume",
            "换手率": "turnover_rate"
        }
        df = df.rename(columns=rename_map)
        df["date"] = pd.to_datetime(df["date"])
        for col in ["open", "close", "high", "low", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        
        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        print(f"[WARN] 获取 {symbol} 历史失败: {e}")
        return None


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_realtime_quote(symbol: str):
    """获取实时行情 - 从实时行情表获取"""
    try:
        # 使用 akshare ETF 实时行情
        df = ak.fund_etf_spot_em()
        if df is None or df.empty:
            return None
        
        row = df[df["代码"] == symbol]
        if row.empty:
            return None
            
        return {
            "price": float(row["最新价"].iloc[0]),
            "open": float(row["今开"].iloc[0]) if "今开" in row.columns else 0,
            "high": float(row["最高"].iloc[0]) if "最高" in row.columns else 0,
            "low": float(row["最低"].iloc[0]) if "最低" in row.columns else 0,
            "pct_chg": float(row["涨跌幅"].iloc[0]),
            "volume": float(row["成交量"].iloc[0]) if "成交量" in row.columns else 0,
            "turnover_rate": float(row["换手率"].iloc[0]) if "换手率" in row.columns else 0,
        }
    except Exception as e:
        print(f"[WARN] 获取 {symbol} 实时行情失败: {e}")
        return None


def calc_macd(df: pd.DataFrame):
    """计算 MACD"""
    if df is None or len(df) < 26:
        return {"dif": 0, "dea": 0, "macd": 0, "signal": "无数据"}
    
    close = df["close"]
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd = (dif - dea) * 2
    
    signal = "金叉" if dif.iloc[-1] > dea.iloc[-1] and dif.iloc[-2] <= dea.iloc[-2] else \
             "死叉" if dif.iloc[-1] < dea.iloc[-1] and dif.iloc[-2] >= dea.iloc[-2] else \
             "多头" if dif.iloc[-1] > dea.iloc[-1] else "空头"
    
    return {
        "dif": round(dif.iloc[-1], 4),
        "dea": round(dea.iloc[-1], 4),
        "macd": round(macd.iloc[-1], 4),
        "signal": signal
    }


def calc_rsi(df: pd.DataFrame, period: int = 14):
    """计算 RSI"""
    if df is None or len(df) < period:
        return {"rsi": 50, "status": "无数据"}
    
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    rsi_val = rsi.iloc[-1]
    status = "超买" if rsi_val > 70 else "超卖" if rsi_val < 30 else "中性"
    
    return {"rsi": round(rsi_val, 2), "status": status}


def calc_bollinger(df: pd.DataFrame, period: int = 20):
    """计算布林带"""
    if df is None or len(df) < period:
        return {"upper": 0, "middle": 0, "lower": 0, "position": "无数据"}
    
    close = df["close"]
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + 2 * std
    lower = middle - 2 * std
    
    current = close.iloc[-1]
    position = "上轨附近" if current > upper.iloc[-1] * 0.98 else \
               "下轨附近" if current < lower.iloc[-1] * 1.02 else "中轨附近"
    
    return {
        "upper": round(upper.iloc[-1], 3),
        "middle": round(middle.iloc[-1], 3),
        "lower": round(lower.iloc[-1], 3),
        "position": position
    }


def calc_ma_trend(df: pd.DataFrame):
    """计算均线趋势"""
    if df is None or len(df) < 60:
        return {"ma5": 0, "ma20": 0, "ma60": 0, "trend": "无数据", "above_ma60": False}
    
    close = df["close"]
    ma5 = float(close.rolling(5).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma60 = float(close.rolling(60).mean().iloc[-1])
    current = float(close.iloc[-1])
    
    trend = "强势" if current > ma5 > ma20 > ma60 else \
            "弱势" if current < ma5 < ma20 < ma60 else "震荡"
    
    return {
        "ma5": round(ma5, 3),
        "ma20": round(ma20, 3),
        "ma60": round(ma60, 3),
        "trend": trend,
        "above_ma60": bool(current > ma60)  # 转换为 Python bool
    }


def analyze_single_etf(symbol: str, spot_df: pd.DataFrame = None):
    """分析单只 ETF
    
    Args:
        symbol: ETF代码
        spot_df: 预先获取的全量实时行情DataFrame，避免重复API调用
    """
    print(f"[INFO] 分析 {symbol}...")
    
    # 获取历史数据
    df = fetch_etf_history(symbol, 120)
    if df is None or df.empty:
        return None
    
    # 从缓存的spot_df获取实时行情，避免重复调用API
    realtime = None
    name = symbol
    
    if spot_df is not None and not spot_df.empty:
        row = spot_df[spot_df["代码"] == symbol]
        if not row.empty:
            name = row["名称"].iloc[0]
            try:
                realtime = {
                    "price": float(row["最新价"].iloc[0]),
                    "open": float(row["今开"].iloc[0]) if "今开" in row.columns else 0,
                    "high": float(row["最高"].iloc[0]) if "最高" in row.columns else 0,
                    "low": float(row["最低"].iloc[0]) if "最低" in row.columns else 0,
                    "pct_chg": float(row["涨跌幅"].iloc[0]),
                    "volume": float(row["成交量"].iloc[0]) if "成交量" in row.columns else 0,
                    "turnover_rate": float(row["换手率"].iloc[0]) if "换手率" in row.columns else 0,
                }
            except Exception as e:
                print(f"[WARN] 解析 {symbol} 实时数据失败: {e}")
    else:
        # 回退到单独API调用
        realtime = fetch_realtime_quote(symbol)
    
    # 计算指标
    analysis = {
        "symbol": symbol,
        "name": name,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "realtime": realtime,
        "macd": calc_macd(df),
        "rsi": calc_rsi(df),
        "bollinger": calc_bollinger(df),
        "ma_trend": calc_ma_trend(df),
        "last_close": float(df["close"].iloc[-1]),
        "pct_20d": round((df["close"].iloc[-1] / df["close"].iloc[-20] - 1) * 100, 2) if len(df) >= 20 else 0,
        "pct_60d": round((df["close"].iloc[-1] / df["close"].iloc[-60] - 1) * 100, 2) if len(df) >= 60 else 0,
    }
    
    return analysis


def main():
    print("=" * 50)
    print(f"[START] 技术分析预计算 - {datetime.now()}")
    print("=" * 50)
    
    results = {}
    
    # 一次性获取所有ETF实时行情，避免重复API调用
    print("[INFO] 获取全量ETF实时行情...")
    try:
        spot_df = ak.fund_etf_spot_em()
        print(f"[INFO] 获取到 {len(spot_df)} 只ETF数据")
    except Exception as e:
        print(f"[WARN] 获取实时行情失败: {e}, 将逐个获取")
        spot_df = None
    
    for symbol in HOT_ETFS:
        try:
            analysis = analyze_single_etf(symbol, spot_df)
            if analysis:
                results[symbol] = analysis
        except Exception as e:
            print(f"[ERROR] 分析 {symbol} 失败: {e}")
    
    # 保存结果
    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "akshare_eastmoney",
        "count": len(results),
        "analyses": results
    }
    
    output_file = DATA_DIR / "analysis_cache.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"[DONE] 已分析 {len(results)} 只 ETF")
    print(f"       保存到 {output_file}")


if __name__ == "__main__":
    main()
