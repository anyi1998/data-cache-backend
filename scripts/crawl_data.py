import os
import sys
import json
from datetime import datetime
from pathlib import Path
import time
import random

# 添加 app 目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

# 在导入 akshare 之前应用代理补丁
from app.utils.proxy_patch import apply_proxy_patch
apply_proxy_patch()

import akshare as ak
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

# 配置请求头
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

def get_random_header():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://fund.eastmoney.com/"
    }

# 输出目录
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
HISTORY_FILE = DATA_DIR / "etf_history.json"

# 增加随机延迟
def delay_request(func):
    def wrapper(*args, **kwargs):
        time.sleep(random.uniform(1.0, 3.0))
        try:
            if hasattr(ak, 'headers'):
                ak.headers = get_random_header()
            return func(*args, **kwargs)
        except Exception as e:
            print(f"[WARN] 请求出错，冷却 5s: {e}")
            time.sleep(5)
            raise e
    return wrapper

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=5, max=20))
@delay_request
def fetch_etf_spot_eastmoney():
    """获取 ETF 实时行情 - 东方财富"""
    print("[INFO] 尝试东方财富数据源...")
    df = ak.fund_etf_spot_em()
    return df

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=3, max=10))
@delay_request
def fetch_etf_spot_tonghuashun():
    """获取 ETF 实时行情 - 同花顺"""
    print("[INFO] 尝试同花顺数据源...")
    df = ak.fund_etf_spot_ths()
    # 同花顺返回字段可能不同，需要统一格式
    return df

def fetch_etf_spot_data():
    """获取 ETF 实时行情 - 多数据源自动切换"""
    print("[INFO] 获取 ETF 实时行情...")
    
    # 数据源列表：按优先级排序
    sources = [
        ("东方财富", fetch_etf_spot_eastmoney),
        ("同花顺", fetch_etf_spot_tonghuashun),
    ]
    
    last_error = None
    for name, fetch_func in sources:
        try:
            df = fetch_func()
            if df is not None and not df.empty:
                print(f"[SUCCESS] {name} 数据获取成功，共 {len(df)} 条")
                return df, name
        except Exception as e:
            print(f"[WARN] {name} 数据源失败: {e}")
            last_error = e
            continue
    
    if last_error:
        raise last_error
    raise Exception("所有数据源都失败了")

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=5))
@delay_request
def fetch_single_history_safe(symbol: str):
    """安全获取单个 ETF 历史数据"""
    try:
        df = ak.fund_etf_hist_em(symbol=symbol, period="daily", adjust="qfq")
        if df is not None and not df.empty:
            return df.tail(120)["收盘"].tolist()
    except:
        pass
    return []

def load_history():
    """加载历史价格数据"""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"data": {}, "last_update": ""}

def save_history(history_data):
    """保存历史价格数据"""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history_data, f, separators=(',', ':')) # 压缩存储
    except Exception as e:
        print(f"[ERROR] 保存历史数据失败: {e}")

def get_sector_from_name(name):
    """根据名称猜测行业"""
    if "酒" in name or "食品" in name or "消费" in name: return "消费"
    if "药" in name or "医疗" in name or "生物" in name or "创新药" in name: return "医药"
    if "芯" in name or "半导体" in name or "电子" in name: return "科技"
    if "车" in name or "电池" in name: return "新能源"
    if "军" in name: return "军工"
    if "金" in name or "银" in name or "矿" in name: return "资源"
    if "红利" in name: return "红利"
    if "恒生" in name or "港" in name: return "港股"
    if "美" in name or "纳" in name or "标普" in name: return "美股"
    return "其他"

def generate_market_data():
    """生成包含 MA 数据的市场数据"""
    # 1. 加载历史数据
    history_store = load_history()
    history_data = history_store.get("data", {})
    last_update_date = history_store.get("last_update", "")
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 2. 获取今日实时行情 (多数据源自动切换)
    result = fetch_etf_spot_data()
    if result is None:
        print("[ERROR] 无法获取行情")
        return None
    df, data_source = result
    if df is None or df.empty:
        print("[ERROR] 数据为空")
        return None
    print(f"[INFO] 使用数据源: {data_source}")

    # 列映射 - 找回更多字段
    col_mapping = {
        "代码": "symbol", 
        "名称": "name", 
        "最新价": "price", 
        "涨跌幅": "pct_chg", 
        "成交量": "volume",
        "成交额": "amount",
        "换手率": "turnover",
        "量比": "vol_ratio",
    }
    for old, new in col_mapping.items():
        if old in df.columns: df[new] = df[old]
    
    # 清洗数据
    numeric_cols = ["price", "pct_chg", "volume", "amount", "turnover", "vol_ratio"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            
    df = df[df["price"] > 0].copy()
    
    # 计算 RPS (当日)
    df["rps_today"] = df["pct_chg"].rank(pct=True) * 100
    
    # 3. 处理增量更新 (计算 MA 和 阶段涨幅)
    rankings = []
    # 只处理 Top 200 或者已有历史数据的，避免无限膨胀
    target_symbols = set(df.head(200)["symbol"].tolist()) | set(history_data.keys())
    
    # 如果是新的一天，需要追加数据
    is_new_day = last_update_date != today_str
    
    print(f"[INFO] 开始计算 MA & RPS (历史记录: {len(history_data)}, 是否新交易日: {is_new_day})")
    
    processed_count = 0
    missing_history = []
    
    # RPS 20/60 通过 DataFrame rank 计算

    for _, row in df.iterrows():
        symbol = str(row["symbol"])
        price = float(row["price"])
        
        # 只处理目标 ETF
        if symbol not in target_symbols:
            continue
            
        prices = history_data.get(symbol, [])
        
        if not prices and processed_count < 150: 
             missing_history.append(symbol)

        if is_new_day:
            prices.append(price)
        else:
            if prices: prices[-1] = price
            else: prices = [price]
        
        # 保持长度 (扩大到 120 天)
        if len(prices) > 130:
            prices = prices[-120:]
            
        history_data[symbol] = prices
        
        # 计算 MA
        ma20 = sum(prices[-20:]) / 20 if len(prices) >= 20 else None
        ma60 = sum(prices[-60:]) / 60 if len(prices) >= 60 else None
        
        # 计算阶段涨幅 (用于 RPS)
        pct_20 = (price - prices[-20]) / prices[-20] * 100 if len(prices) >= 20 else None
        pct_60 = (price - prices[-60]) / prices[-60] * 100 if len(prices) >= 60 else None
        
        # 构造输出对象 (暂存阶段涨幅)
        item = {
            "symbol": symbol,
            "name": row["name"],
            "price": price,
            "pct_chg": row["pct_chg"],
            "rps_today": row["rps_today"],
            "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "industry": get_sector_from_name(row["name"]),
            "MA20": round(ma20, 3) if ma20 else None,
            "MA60": round(ma60, 3) if ma60 else None,
            "volume": row.get("volume"),
            "amount": row.get("amount"),
            "turnover": row.get("turnover"),
            "vol_ratio": row.get("vol_ratio"),
            "_pct_20": pct_20, # 临时字段
            "_pct_60": pct_60  # 临时字段
        }
        rankings.append(item)
        processed_count += 1
    
    # 计算 RPS 20 / 60
    # 将 rank 算出来放回 item
    df_rank = pd.DataFrame(rankings)
    if not df_rank.empty:
        if "_pct_20" in df_rank.columns:
            df_rank["rps_20"] = df_rank["_pct_20"].rank(pct=True) * 100
        if "_pct_60" in df_rank.columns:
            df_rank["rps_60"] = df_rank["_pct_60"].rank(pct=True) * 100
            
        # 更新 rankings list
        rankings = df_rank.to_dict("records")
        # 清理临时字段
        for r in rankings:
            r.pop("_pct_20", None)
            r.pop("_pct_60", None)
            # 处理 NaN
            if pd.isna(r.get("rps_20")): r["rps_20"] = None
            if pd.isna(r.get("rps_60")): r["rps_60"] = None

    # 4. 尝试补充缺失的历史数据
    if missing_history:
        print(f"[INFO] 发现 {len(missing_history)} 个 ETF 缺失历史数据，加速补全前 30 个...")
        for sym in missing_history[:30]:
            hist = fetch_single_history_safe(sym)
            if hist:
                history_data[sym] = hist
                print(f"  > 已补全 {sym} ({len(hist)}天)")
            time.sleep(2)
    
    # 更新历史文件
    save_history({"data": history_data, "last_update": today_str})
    
    # 5. 组装最终结果
    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rankings": sorted(rankings, key=lambda x: x["rps_today"], reverse=True)[:100],
        "recommend": [],
        "crash": []
    }
    
    # 推荐逻辑 - 修复 NaN 处理
    for r in result["rankings"]:
        rps = r.get("rps_today", 0) or 0
        pct = r.get("pct_chg", 0) or 0
        price = r.get("price", 0) or 0
        ma20 = r.get("MA20")
        
        # 检查 MA20 是否是有效数字
        ma20_valid = ma20 is not None and not (isinstance(ma20, float) and pd.isna(ma20))
        above_ma20 = ma20_valid and price > ma20
        
        # 推荐条件：高RPS + 涨幅适中 + (站上MA20 或 MA20不可用时仅凭RPS)
        # 如果 MA20 可用，需要站上；如果不可用，仅凭 RPS > 90 + 涨幅 < 5%
        if rps > 85 and pct < 7 and pct > -3:
            if above_ma20:
                # 完美条件：站上20日线
                r["recommend_reason"] = "站上MA20"
                result["recommend"].append(r)
            elif not ma20_valid and rps > 90 and pct > 0 and pct < 5:
                # 降级条件：无MA数据但RPS极高+温和上涨
                r["recommend_reason"] = "动量强势"
                result["recommend"].append(r)
        
        # 预警：高RPS + 大跌
        if rps > 90 and pct < -2:
            result["crash"].append(r)
            
    result["recommend"] = result["recommend"][:15]
    result["crash"] = result["crash"][:10]
    
    return result

def main():
    print("="*50)
    print(f"[START] 增量爬虫 - {datetime.now()}")
    
    data = generate_market_data()
    if not data: return
    
    out_file = DATA_DIR / "latest.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"[DONE] 完成。MA20覆盖率: {len([x for x in data['rankings'] if x.get('MA20')])}/{len(data['rankings'])}")

if __name__ == "__main__":
    main()
