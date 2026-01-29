#!/usr/bin/env python3
"""
GitHub Actions 爬虫脚本
定时获取 ETF 市场数据并保存为 JSON
"""
import os
import sys
import json
from datetime import datetime
from pathlib import Path

# 添加 app 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 在导入 akshare 之前应用代理补丁
from app.utils.proxy_patch import apply_proxy_patch
apply_proxy_patch()

import akshare as ak
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

# 配置请求头，减少反爬虫概率
CUSTOM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 尝试配置 akshare 的请求头
try:
    if hasattr(ak, 'headers'):
        ak.headers = CUSTOM_HEADERS
except:
    pass

# 输出目录
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_etf_spot_data():
    """获取 ETF 实时行情数据"""
    print("[INFO] 获取 ETF 实时行情...")
    df = ak.fund_etf_spot_em()
    return df


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_etf_history(symbol: str, days: int = 120):
    """获取单只 ETF 历史数据"""
    try:
        df = ak.fund_etf_hist_em(symbol=symbol, period="daily", adjust="qfq")
        if df is not None and not df.empty:
            return df.tail(days)
    except Exception as e:
        print(f"[WARN] 获取 {symbol} 历史失败: {e}")
    return None


def calc_rps(df: pd.DataFrame, period: int = 120) -> pd.DataFrame:
    """计算 RPS 相对强度"""
    if df is None or df.empty:
        return df
    
    # 计算涨跌幅
    df = df.copy()
    if "涨跌幅" in df.columns:
        df["pct_chg"] = pd.to_numeric(df["涨跌幅"], errors="coerce")
    elif "最新价" in df.columns and "开盘价" in df.columns:
        df["pct_chg"] = (df["最新价"] - df["开盘价"]) / df["开盘价"] * 100
    
    # 计算 RPS
    if "pct_chg" in df.columns:
        df["rps"] = df["pct_chg"].rank(pct=True) * 100
    
    return df


def generate_market_data():
    """生成市场数据 JSON"""
    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "akshare_eastmoney",  # 数据来源标识
        "rankings": [],
        "market_temperature": {},
        "recommend": [],
        "crash": []
    }
    
    try:
        # 1. 获取 ETF 实时行情
        df = fetch_etf_spot_data()
        if df is None or df.empty:
            print("[ERROR] 无法获取 ETF 数据")
            return result
        
        print(f"[INFO] 获取到 {len(df)} 只 ETF")
        
        # 2. 处理数据
        # 重命名列
        col_mapping = {
            "代码": "symbol",
            "名称": "name",
            "最新价": "price",
            "涨跌幅": "pct_chg",
            "成交量": "volume",
            "换手率": "turnover"
        }
        
        for old, new in col_mapping.items():
            if old in df.columns:
                df[new] = df[old]
        
        # 转换数值
        for col in ["price", "pct_chg", "volume", "turnover"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        
        # 过滤无效数据
        df = df[df["price"].notna() & (df["price"] > 0)]
        
        # 计算 RPS (当日相对强度, 基于今日涨跌幅在全市场的百分位排名)
        df["rps_today"] = df["pct_chg"].rank(pct=True) * 100
        
        # 3. 生成排名数据
        rankings = []
        for _, row in df.head(100).iterrows():
            rankings.append({
                "symbol": str(row.get("symbol", "")),
                "name": str(row.get("name", "")),
                "price": float(row.get("price", 0)),
                "pct_chg": float(row.get("pct_chg", 0)) if pd.notna(row.get("pct_chg")) else 0,
                "rps_today": float(row.get("rps_today", 50)),  # 当日相对强度
            })
        
        result["rankings"] = sorted(rankings, key=lambda x: x["rps_today"], reverse=True)
        
        # 4. 计算市场温度
        up_count = len(df[df["pct_chg"] > 0])
        down_count = len(df[df["pct_chg"] < 0])
        total = up_count + down_count
        
        if total > 0:
            temperature = int((up_count / total) * 100)
        else:
            temperature = 50
        
        if temperature >= 70:
            status = "过热"
            advice = "市场情绪高涨，注意风险"
        elif temperature >= 55:
            status = "偏热"
            advice = "适度参与，控制仓位"
        elif temperature >= 45:
            status = "中性"
            advice = "观望为主，精选个股"
        elif temperature >= 30:
            status = "偏冷"
            advice = "可逐步建仓"
        else:
            status = "极冷"
            advice = "恐慌出现，可能是机会"
        
        result["market_temperature"] = {
            "temperature": temperature,
            "status": status,
            "advice": advice,
            "up_count": up_count,
            "down_count": down_count,
            "above_ma20_pct": temperature  # 简化处理
        }
        
        # 5. 生成推荐列表 (当日RPS > 80 且今日涨幅 < 5%)
        high_rps = [r for r in result["rankings"] if r["rps_today"] > 80 and r["pct_chg"] < 5]
        result["recommend"] = high_rps[:15]
        
        # 6. 生成崩盘观察列表 (当日RPS > 90 且今日跌幅 > 3%)
        crash_watch = [r for r in result["rankings"] if r["rps_today"] > 90 and r["pct_chg"] < -3]
        result["crash"] = crash_watch[:10]
        
        print(f"[INFO] 生成 {len(result['rankings'])} 条排名, {len(result['recommend'])} 条推荐")
        
    except Exception as e:
        print(f"[ERROR] 生成数据失败: {e}")
        import traceback
        traceback.print_exc()
    
    return result


def main():
    print("=" * 50)
    print(f"[START] ETF 数据爬取 - {datetime.now()}")
    print("=" * 50)
    
    # 生成数据
    data = generate_market_data()
    
    # 保存到 JSON
    output_file = DATA_DIR / "latest.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"[DONE] 数据已保存到 {output_file}")
    print(f"       生成时间: {data['generated_at']}")
    print(f"       排名数量: {len(data['rankings'])}")
    print(f"       市场温度: {data['market_temperature'].get('temperature', 'N/A')}°")


if __name__ == "__main__":
    main()
