import streamlit as st
import pandas as pd
from duckduckgo_search import DDGS
import re
import time

# --- 页面配置 ---
st.set_page_config(page_title="尾货智能选品雷达", page_icon="📦", layout="wide")

# --- 核心逻辑：品牌分级数据库 ---
BRAND_TIERS = {
    "S": ["APPLE", "SONY", "DYSON", "LEGO", "NINTENDO", "MAKITA", "DEWALT", "BOSE", "JBL", "ROLEX", "LV"],
    "A": ["SAMSUNG", "SHARK", "NINJA", "HP", "DELL", "NIKE", "KITCHENAID", "MILWAUKEE", "LG", "CUISINART", "GARMIN"],
    "B": ["BISSELL", "BLACK+DECKER", "TCL", "HISENSE", "ROKU", "VIZIO", "CRAFTSMAN", "RYOBI", "ANKER"]
}

def get_brand_score(brand_name):
    if not brand_name:
        return 0, "未知"
    upper_brand = brand_name.upper()
    for brand in BRAND_TIERS["S"]:
        if brand in upper_brand: return 40, "S级 (硬通货)"
    for brand in BRAND_TIERS["A"]:
        if brand in upper_brand: return 30, "A级 (知名品牌)"
    for brand in BRAND_TIERS["B"]:
        if brand in upper_brand: return 15, "B级 (二线品牌)"
    return 0, "C级 (普通/杂牌)"

def search_market_price(product_query):
    """
    使用 DuckDuckGo 搜索产品价格，作为 Amazon 价格的免费替代方案
    """
    try:
        with DDGS() as ddgs:
            # 搜索关键词：产品名 + price + amazon
            results = list(ddgs.text(f"{product_query} price amazon", max_results=5))
            
            # 简单的正则提取价格
            prices = []
            for r in results:
                # 寻找 $xx.xx 的格式
                found = re.findall(r'\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', r['body'])
                if found:
                    # 转换为浮点数
                    for p in found:
                        try:
                            price_float = float(p.replace(',', ''))
                            if price_float > 10: # 过滤掉太便宜的配件价格干扰
                                prices.append(price_float)
                        except:
                            continue
            
            if prices:
                # 取中位数或出现最多的价格，这里简单取平均值作为参考
                avg_price = sum(prices) / len(prices)
                return round(avg_price, 2), results[0]['href']
            else:
                return None, None
    except Exception as e:
        return None, None

# --- UI 界面构建 ---

st.title("📦 尾货智能选品雷达 (Liquidation Radar)")
st.markdown("""
<style>
    .big-font { font-size:20px !important; }
    .metric-card { background-color: #f0f2f6; padding: 15px; border-radius: 10px; border-left: 5px solid #ff4b4b; }
</style>
""", unsafe_allow_html=True)

st.info("💡 提示：输入产品名称，系统将自动搜索全网价格并根据【金字塔模型】打分。")

# --- 侧边栏 ---
with st.sidebar:
    st.header("⚙️ 参数设置")
    input_method = st.radio("输入方式", ["手动输入文字", "📸 上传图片 (开发中)"])
    st.caption("目前 MVP 版本仅支持文字搜索，图片识别需要接入 GPT-4 Vision API。")

# --- 主区域 ---
col1, col2 = st.columns([1, 1.5])

with col1:
    st.subheader("1. 输入产品信息")
    product_name = st.text_input("产品全名 (品牌+型号)", placeholder="例: Ninja AF101 Air Fryer")
    product_category = st.selectbox("产品品类", 
        options=["电子/家电 (通用)", "知名工具", "特定家电", "家居/户外", "冷门/配件"],
        index=0
    )
    
    my_price = st.number_input("你的拿货/拟售价 ($)", min_value=0.0, value=0.0, step=1.0)
    
    analyze_btn = st.button("🚀 开始智能分析", type="primary")

# --- 分析逻辑 ---
if analyze_btn and product_name and my_price > 0:
    with st.spinner(f'正在全网检索 "{product_name}" 的市场行情...'):
        # 1. 品牌分析
        brand_score, brand_tier_name = get_brand_score(product_name)
        
        # 2. 价格搜索
        market_price, link = search_market_price(product_name)
        
        # 如果没搜到价格，让用户手动补充（容错）
        if market_price is None:
            st.warning("⚠️ 自动搜索未找到确切价格，请手动参考 Amazon。暂按 $100 计算。")
            market_price = 100.0
            link = "https://www.amazon.com/s?k=" + product_name.replace(" ", "+")
        
        # 3. 计算维度
        # A. 品类分
        cat_map = {"电子/家电 (通用)": 20, "知名工具": 15, "特定家电": 10, "家居/户外": 5, "冷门/配件": -10}
        cat_score = cat_map.get(product_category, 0)
        
        # B. 价格优势分
        discount_rate = 0
        price_score = 0
        if market_price > 0:
            discount_rate = ((market_price - my_price) / market_price) * 100
            if discount_rate >= 70: price_score = 40
            elif discount_rate >= 50: price_score = 30
            elif discount_rate >= 30: price_score = 10
        
        # C. 价值感分
        value_score = 10 if market_price > 200 else (5 if market_price > 100 else 0)
        
        # D. 总分
        total_score = min(100, max(0, brand_score + cat_score + price_score + value_score))

    # --- 结果展示 ---
    with col2:
        st.subheader("2. 智能分析报告")
        
        # 顶部大分
        score_color = "green" if total_score >= 80 else ("orange" if total_score >= 60 else "red")
        st.markdown(f"""
        <div style="text-align: center; padding: 20px; background-color: #fff; border-radius: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
            <h2 style="margin:0; color: #666;">选品推荐指数</h2>
            <h1 style="font-size: 60px; margin: 0; color: {score_color};">{total_score} 分</h1>
        </div>
        """, unsafe_allow_html=True)
        
        # 详细数据卡片
        st.markdown("### 📊 关键指标")
        m1, m2, m3 = st.columns(3)
        m1.metric("参考市场价 (Est.)", f"${market_price}", delta_color="off")
        m2.metric("利润空间/折扣", f"-{int(discount_rate)}%", delta=f"${market_price - my_price:.0f} 差价")
        m3.metric("品牌评级", brand_tier_name)
        
        if link:
            st.caption(f"🔗 [点击查看搜索来源]({link})")

        # 操盘建议
        st.markdown("### 💡 操盘建议")
        if total_score >= 80:
            st.success("**【S级 - 流量钩子】**\n\n这是一个绝对的爆品。哪怕不赚钱，也要用它把客户引流到私域或店铺里！\n* 建议话术：Only $"+str(my_price)+"! (Amazon is $"+str(market_price)+")")
        elif total_score >= 60:
            st.info("**【A级 - 利润核心】**\n\n价格和品牌都很不错，适合作为主力利润款上架销售。\n* 建议：检查包装，确保功能完好。")
        elif total_score >= 40:
            st.warning("**【B级 - 凑单/盲盒】**\n\n单独运费不划算，建议放在 Bin Store 或作为 $10 专区商品。")
        else:
            st.error("**【C级 - 建议放弃】**\n\n无品牌优势且价格一般，建议线下打包处理，不要浪费线上运营精力。")

else:
    with col2:
        st.markdown("### 👋 欢迎使用")
        st.write("请在左侧输入产品信息，点击按钮开始分析。")
        st.write("本工具将模拟市场搜索，为您提供基于数据的选品决策。")
