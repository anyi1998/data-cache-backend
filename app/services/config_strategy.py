"""
ETF 分析策略配置文件
存储所有策略参数、阈值和黑名单配置，实现逻辑与配置解耦。
"""

# ==================== 策略参数阈值 ====================
STRATEGY_PARAMS = {
    "BOLLINGER": {
        "SQUEEZE_THRESHOLD": 8.0,   # 极度收敛阈值 (带宽 < 8%)
        "OVERHEAT_THRESHOLD": 20.0, # 过热阈值 (带宽 > 20%)
        "PERCENTILE_LOW": 10,       # 极低分位 (即将变盘)
        "PERCENTILE_HIGH": 90       # 极高分位 (波动放大)
    },
    "RSI": {
        "EXTREME_OVERBOUGHT": 75,   # 极度超买
        "OVERBOUGHT": 70,           # 超买
        "OVERSOLD": 30,             # 超卖
        "EXTREME_OVERSOLD": 25      # 极度超卖 (黄金坑)
    },
    "KDJ": {
        "LOW_GOLDEN_CROSS": 40,     # 低位金叉阈值 (K < 40)
        "HIGH_DEATH_CROSS": 80,     # 高位死叉阈值 (K > 80)
        "PASSIVATION_HIGH": 100,    # 高位钝化 (J > 100)
        "PASSIVATION_LOW": 0        # 低位钝化 (J < 0)
    },
    "RPS": {
        "STRONG_THRESHOLD": 80,     # 强势线 (RPS > 80)
        "WEAK_THRESHOLD": 30,       # 弱势线 (RPS < 30)
        "TOP_RANK_LIMIT": 150,      # 计算RPS时参与排名的ETF数量限制
        "THREADS_COUNT": 16         # 并发请求线程数
    },
    "VOLUME": {
        "RATIO_ATTACK": 2.0,        # 放量进攻 (量比 > 2.0)
        "RATIO_LOW": 0.6,           # 极度缩量 (量比 < 0.6)
        "RATIO_WARNING": 0.8,       # 无量上涨警告线
        "FAKE_VOL_AMPLITUDE": 1.0   # 假放量振幅阈值 (量比>2但振幅<1.0%为对倒/高位出货)
    },
    "BIAS": {
        "EXTREME_HIGH": 15.0,       # 极度超买乖离率 (强烈止盈, ETF 15%已极高)
        "HIGH": 10.0,               # 高乖离率 (建议止盈/减仓)
        "MEDIUM": 6.0,              # 中等乖离率 (可考虑分批高抛)
        "EXTREME_LOW": -15.0        # 极度超跌乖离率 (可博反弹)
    },
    "SENTIMENT": {
        "TURNOVER_OVERHEAT": 15.0,  # 换手率过热
        "TURNOVER_ACTIVE_MIN": 3.0, # 活跃下限
        "TURNOVER_ACTIVE_MAX": 10.0,# 活跃上限
        "TURNOVER_ZOMBIE": 0.5      # 僵尸基金阈值
    },
    "ATR": {
        "MULTIPLIER": 2.0,          # ATR 止损倍数
        "VOLATILITY_EXTREME": 4.0,  # 极高波动率 (>4%)
        "VOLATILITY_HIGH": 2.5,     # 高波动率 (>2.5%)
        "VOLATILITY_MEDIUM": 1.5    # 中波动率 (>1.5%)
    },
    "MACD": {
        "DIVERGENCE_PRICE_RATIO": 0.98, # 价格接近新高的比例
        "DIVERGENCE_DIF_RATIO": 0.85    # DIF未创新高的比例
    },
    # ==================== 双模态决策引擎 阈值 ====================
    "DUAL_MODE": {
        "TREND_RPS_THRESHOLD": 90,      # 主升浪模式 RPS 阈值
        "SHOCK_RPS_THRESHOLD": 90,      # 震荡市模式 RPS 阈值 (低于此进入震荡)
        "SHOCK_BANDWIDTH_MAX": 12,      # 震荡市 布林带宽上限
        "PULLBACK_PERCENTILE_LOW": 35,  # 主升浪回踩分位 (低吸区)
        "BREAKOUT_PCT_MIN": 3.0,        # 纠错机制: 大阳线涨幅下限
        "BREAKOUT_VOL_RATIO": 1.5,      # 纠错机制: 放量倍数下限
        "BREAKOUT_RPS_JUMP": 90         # 纠错机制: RPS飙升阈值
    },
    # ==================== Alpha 相对强度 阈值 ====================
    "ALPHA": {
        "LEADER_THRESHOLD": 1.5,        # 领跑大盘阈值
        "LAGGARD_THRESHOLD": -0.5       # 弱于大盘阈值
    },
    # ==================== IOPV 溢价率 阈值 ====================
    "IOPV": {
        "PREMIUM_WARNING": 3.0,         # 溢价警告阈值
        "DISCOUNT_OPPORTUNITY": -1.0    # 折价机会阈值
    },
    # ==================== 熔断 阈值 ====================
    "CIRCUIT_BREAKER": {
        "DAILY_DROP_LIMIT": -3.0,       # 日跌幅熔断
        "TURNOVER_OVERHEAT": 15.0       # 换手率过热熔断
    },
    # ==================== 均线回归策略 (脑总战法) ====================
    "MEAN_REVERSION": {
        "RPS_THRESHOLD": 85,            # 强势品种RPS阈值
        "RPS_CRAZY_BULL": 95,           # 疯牛阈值 (MA5坐火箭模式)
        "BIAS20_SELL_THRESHOLD": 15.0,  # Bias20超过此值触发止盈
        "BIAS60_SELL_THRESHOLD": 20.0,  # Bias60超过此值触发止盈
        "BIAS20_BUY_MAX": 2.0,          # Bias20低于此值才考虑买入
        "MA_TOUCH_TOLERANCE": 0.01,     # 回踩容忍度 (1%)
        "MA60_SLOPE_DAYS": 5            # 计算MA60斜率的天数
    }
}

# ==================== 加载外部配置 (Override) ====================
import json
import os

def load_external_config():
    """尝试从 json 文件加载配置以覆盖默认值"""
    # 路径：backend/app/config.json
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config.json")
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                external_config = json.load(f)
                
            # 深度合并配置
            for section, params in external_config.items():
                if section in STRATEGY_PARAMS:
                    STRATEGY_PARAMS[section].update(params)
            print(f"[INFO] 已加载外部策略配置: {config_path}")
        except Exception as e:
            print(f"[WARN] 加载外部配置失败: {e}")

# 执行加载
load_external_config()

# ==================== 资产黑名单 (定价权防火墙) ====================
# 这些品种的定价权不在 A 股资金面，RPS 动量模型不适用
ASSET_BLACKLIST = {
    # 贵金属/商品 → 看期货价差
    "黄金": "黄金价格由国际金价决定，建议查看COMEX黄金期货或溢价率",
    "白银": "白银价格由国际银价决定，建议查看COMEX白银期货",
    "豆粕": "大宗商品ETF，建议查看期货主力合约",
    "原油": "原油价格由WTI/布伦特决定，建议查看原油期货",
    "能源化工": "商品类ETF，建议查看期货价格",
    # 跨境 ETF → 看美股/港股
    "纳指": "跟踪纳斯达克指数，建议直接看美股QQQ",
    "标普": "跟踪标普500指数，建议直接看美股SPY",
    "恒生": "跟踪港股恒生指数，建议看港股行情",
    "中概": "跟踪中概股，价格由美股决定",
    "日经": "跟踪日本股市，建议看日经225期货",
    "德国": "跟踪德国DAX，建议看欧洲市场",
    # 债券 → 看利率
    "国债": "债券ETF受利率影响，建议关注央行政策和国债收益率",
    "企债": "债券ETF受利率影响",
    "可转债": "可转债有独特定价逻辑，建议使用转债专用分析"
}

# ==================== 代码前缀过滤 (Gatekeeper) ====================
CODE_PREFIX_BLACKLIST = {
    "513": ("跨境ETF (QDII)", "定价权在海外市场", "请直接查看 QQQ/SPY 或 恒生科技 K线"),
    "518": ("商品ETF (贵金属)", "定价权在期货市场", "请查看 COMEX黄金/白银 期货走势"),
    "511": ("债券/货币ETF", "定价权在央行/利率", "请关注国债收益率/央行政策"),
}
