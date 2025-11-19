import streamlit as st
import pandas as pd
from duckduckgo_search import DDGS
import re
import time
import io

# --- 页面配置 ---
st.set_page_config(page_title="尾货智能选品雷达 Pro", page_icon="📦", layout="wide")

# --- 核心逻辑库 ---

# 1. 品牌数据库
BRAND_TIERS = {
    "S": ["APPLE", "SONY", "DYSON", "LEGO", "NINTENDO", "MAKITA", "DEWALT", "BOSE", "JBL", "ROLEX", "LV", "HERMES"],
    "A": ["SAMSUNG", "SHARK", "NINJA", "HP", "DELL", "NIKE", "KITCHENAID", "MILWAUKEE", "LG", "CUISINART", "GARMIN", "ASUS", "LENOVO"],
    "B": ["BISSELL", "BLACK+DECKER", "TCL", "HISENSE", "ROKU", "VIZIO", "CRAFTSMAN", "RYOBI", "ANKER", "LOGITECH"]
}

# 2. 品类分数映射
CAT_SCORE_MAP = {
    "电子/家电 (通用)": 20, 
    "知名工具": 15, 
    "特定家电": 10, 
    "家居/户外": 5, 
    "冷门/配件": -10
}

def get_brand_score(brand_name):
    if not brand_name:
        return 0, "未知"
    upper_brand = str(brand_name).upper()
    for brand in BRAND_TIERS["S"]:
        if brand in upper_brand: return 40, "S级"
    for brand in BRAND_TIERS["A"]:
        if brand in upper_brand: return 30, "A级"
    for brand in BRAND_TIERS["B"]:
        if brand in upper_brand: return 15, "B级"
    return 0, "C级"

def search_market_price(product_query):
    """联网搜索价格"""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(f"{product_query} price amazon", max_results=3))
            prices = []
            for r in results:
                found = re.findall(r'\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', r['body'])
                if found:
                    for p in found:
                        try:
                            price_float = float(p.replace(',', ''))
                            if price_float > 10: prices.append(price_float)
                        except: continue
            
            if prices:
                avg_price = sum(prices) / len(prices)
                return round(avg_price, 2), results[0]['href']
            return 0, None
    except Exception:
        return 0, None

def analyze_item(product_name, category, my_price):
    """核心分析函数 (供单个和批量共用)"""
    # 1. 品牌分
    brand_score, brand_tier = get_brand_score(product_name)
    
    # 2. 价格搜索 (如果单价过低，可能是配件，搜索可能不准)
    market_price, link = search_market_price(product_name)
    
    # 如果搜不到，默认给一个占位符，避免报错
    if market_price == 0:
        market_price = my_price * 2 # 假设你是半价拿的 (保守估计)
        note = "⚠️ 未搜到确切价格，估算值"
    else:
        note = "✅ 联网查询成功"

    # 3. 计算维度
    cat_score = CAT_SCORE_MAP.get(category, 0)
    
    discount_rate = 0
    price_score = 0
    if market_price > 0 and my_price > 0:
        discount_rate = ((market_price - my_price) / market_price) * 100
        if discount_rate >= 70: price_score = 40
        elif discount_rate >= 50: price_score = 30
        elif discount_rate >= 30: price_score = 10
    
    value_score = 10 if market_price > 200 else (5 if market_price > 100 else 0)
    
    total_score = min(100, max(0, brand_score + cat_score + price_score + value_score))
    
    # 评级建议
    if total_score >= 80: suggestion = "S级-引流钩子 (必做广告)"
    elif total_score >= 60: suggestion = "A级-利润核心 (重点上架)"
    elif total_score >= 40: suggestion = "B级-凑单/盲盒 ($10区)"
    else: suggestion = "C级-线下处理 (建议放弃)"

    return {
        "总分": total_score,
        "评级建议": suggestion,
        "品牌等级": brand_tier,
        "全网参考价": market_price,
        "预估折扣力度": f"{int(discount_rate)}% OFF",
        "备注": note,
        "链接": link
    }

# --- UI 界面 ---
st.title("📦 尾货智能选品雷达 Pro")
st.markdown("支持 **单品交互** 与 **Excel批量处理** 双模式")

# 使用 Tabs 分割两种模式
tab1, tab2 = st.tabs(["🔍 单品实时交互", "📄 Excel 批量上传"])

# ==========================================
# 模式一：单品交互
# ==========================================
with tab1:
    col1, col2 = st.columns([1, 1.5])
    with col1:
        st.info("输入单个产品信息进行快速测试。")
        s_name = st.text_input("产品全名 (Brand + Model)", "Ninja AF101 Air Fryer")
        s_cat = st.selectbox("产品品类", list(CAT_SCORE_MAP.keys()))
        s_price = st.number_input("你的拿货/拟售价 ($)", value=40.0)
        s_btn = st.button("🚀 开始分析", key="single_btn")

    if s_btn and s_name:
        with st.spinner("正在全网比价中..."):
            res = analyze_item(s_name, s_cat, s_price)
        
        with col2:
            st.metric("智能评分", f"{res['总分']} 分", delta=res['评级建议'])
            st.write(f"**全网参考价:** ${res['全网参考价']}")
            st.write(f"**折扣力度:** {res['预估折扣力度']}")
            st.caption(res['备注'])
            if res['链接']: st.markdown(f"[查看来源]({res['链接']})")

# ==========================================
# 模式二：Excel 批量处理
# ==========================================
with tab2:
    st.markdown("### 批量选品处理中心")
    st.markdown("""
    1. 请上传 Excel (.xlsx) 文件。
    2. 表格必须包含以下表头 (顺序不限)：
       * `产品全名` (例如: Apple AirPods Pro)
       * `产品品类` (填: 电子/家电, 知名工具, 特定家电, 家居/户外, 或 冷门/配件)
       * `拟售价` (数字, 例如: 50)
    """)

    # 1. 下载模板功能
    sample_data = pd.DataFrame({
        "产品全名": ["Sony WH-1000XM4 Headphones", "Generic USB Cable", "Dyson V10 Vacuum"],
        "产品品类": ["电子/家电 (通用)", "冷门/配件", "电子/家电 (通用)"],
        "拟售价": [100, 2, 150]
    })
    
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        sample_data.to_excel(writer, index=False, sheet_name='Sheet1')
    
    st.download_button(
        label="📥 下载 Excel 模版",
        data=buffer,
        file_name="选品模版.xlsx",
        mime="application/vnd.ms-excel"
    )

    # 2. 上传文件
    uploaded_file = st.file_uploader("上传你的尾货清单", type=["xlsx"])

    if uploaded_file:
        df = pd.read_excel(uploaded_file)
        st.write("预览上传的数据 (前5行):")
        st.dataframe(df.head())

        # 检查列名
        required_cols = ["产品全名", "产品品类", "拟售价"]
        if not all(col in df.columns for col in required_cols):
            st.error(f"❌ 列名不匹配！请确保包含: {required_cols}")
        else:
            if st.button("⚡ 开始批量分析 (速度取决于网络)"):
                
                results_list = []
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                total_rows = len(df)
                
                for index, row in df.iterrows():
                    # 更新进度
                    status_text.text(f"正在处理第 {index+1}/{total_rows} 个: {row['产品全名']}...")
                    progress_bar.progress((index + 1) / total_rows)
                    
                    # 执行分析
                    analysis = analyze_item(
                        row['产品全名'], 
                        row.get('产品品类', '电子/家电 (通用)'), 
                        float(row['拟售价'])
                    )
                    
                    # 合并结果
                    row_data = row.to_dict()
                    row_data.update(analysis) # 把分析结果追加到原数据后
                    results_list.append(row_data)
                    
                    # ⚠️ 礼貌延时，防止触发反爬虫封锁
                    time.sleep(1.0) 

                # 完成
                final_df = pd.DataFrame(results_list)
                st.success("✅ 批量处理完成！")
                
                # 展示结果
                st.dataframe(final_df)
                
                # 导出结果
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    final_df.to_excel(writer, index=False, sheet_name='分析结果')
                
                st.download_button(
                    label="📥 下载分析结果 (.xlsx)",
                    data=output,
                    file_name="智能选品结果.xlsx",
                    mime="application/vnd.ms-excel"
                )
