import streamlit as st
import pandas as pd
from duckduckgo_search import DDGS
import re
import time
import io
import openai
import json
import base64

# --- 页面配置 ---
st.set_page_config(page_title="尾货智能选品雷达 (AI Vision版)", page_icon="👁️", layout="wide")

# --- 全局缓存 (避免重复计费) ---
if 'ai_cache' not in st.session_state:
    st.session_state.ai_cache = {}

# --- 核心逻辑 1: AI Vision 识别 & 估价 ---
def encode_image_to_base64(uploaded_file):
    """将Streamlit上传的图片文件编码为Base64字符串"""
    if uploaded_file is not None:
        return base64.b64encode(uploaded_file.read()).decode("utf-8")
    return None

def get_ai_product_info_from_image(base64_image, api_key, text_input=None):
    """
    调用 OpenAI GPT-4o Vision API 识别图片，并模拟搜索/评估可替代性
    """
    # 1. 检查 Key
    if not api_key:
        return None, None, "❓ 未配置API Key", "N/A", 0, 0

    client = openai.OpenAI(api_key=api_key)
    
    # 2. 构造提示词
    messages_content = []
    
    # 如果有图片
    if base64_image:
        messages_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}", "detail": "low"} # "low" 模式更省钱
        })

    # 主要文字提示，引导AI识别和模拟判断
    main_text_prompt = f"""
    You are a professional liquidation merchandise expert in the US market, specialized in product identification, market value estimation, and assessing substitutability for generic or unbranded items.

    Analyze the product shown in the image (and potentially provided text input "{text_input}" if available).

    Tasks:
    1.  **Identify Product:** Determine the product type, its brand, and model if possible.
    2.  **Estimate Market Price:** Based on its appearance, identified brand/model (or similar generic products if the brand is unknown), estimate its typical retail price on Amazon or similar platforms. Assume it's new/open-box condition. If the brand is unknown, search for 'similar product [type] price amazon'.
    3.  **Assess Substitutability (可替代性):** For products where the brand is unknown or generic, assess its substitutability in a low-price liquidation scenario (e.g., if it's a generic USB cable, it's highly substitutable; if it's a unique tool, less so).
        - "High": (10 points) Generic, common, easily replaced by any other similar product (e.g., plain mug, basic USB cable, unbranded socks). High demand at low price.
        - "Medium": (5 points) Some specific features, but can be replaced by other brands with similar features (e.g., basic blender, generic power bank, unbranded headphones).
        - "Low": (0 points) Unique, specific brand features, or complex items where brand matters significantly (e.g., specific tool attachments, high-end electronics, branded clothing). Brand is key, hard to substitute.
    4.  **Classify Brand Tier:** Based on US Resale Value/Liquidity for the detected/estimated brand (S, A, B, C).
        - "S": Luxury, High-End Tech/Tool (40 points)
        - "A": Well-known, Reliable (30 points)
        - "B": Budget, Store Brands (15 points)
        - "C": Generic, Unknown, Low Value (0 points)
    5.  **Provide Reason:** A brief explanation in Chinese for the brand tier and price estimation.

    Output strictly in JSON format:
    ```json
    {{
        "product_type": "Detected Product Type (e.g., Air Fryer, Bluetooth Speaker)",
        "brand_name": "Detected or Estimated Brand (e.g., Ninja, Generic)",
        "model_name": "Detected Model (if any)",
        "estimated_market_price": 0.0,
        "substitutability": "High" or "Medium" or "Low",
        "brand_tier": "S" or "A" or "B" or "C",
        "reason": "简要说明品牌评级和价格估算的理由。"
    }}
    ```
    """
    messages_content.append({"type": "text", "text": main_text_prompt})

    # 缓存 Key (图片 + 文字)
    cache_key = (base64_image[:50] if base64_image else "") + (text_input or "") 
    if cache_key in st.session_state.ai_cache:
        return st.session_state.ai_cache[cache_key]

    try:
        response = client.chat.completions.create(
            model="gpt-4o", # 使用 gpt-4o 获得更好的视觉识别能力
            messages=[{"role": "user", "content": messages_content}],
            response_format={"type": "json_object"},
            temperature=0.0 # 保持结果稳定
        )
        
        data = json.loads(response.choices[0].message.content)

        # 映射分数
        brand_score_map = {"S": 40, "A": 30, "B": 15, "C": 0}
        substitutability_score_map = {"High": 10, "Medium": 5, "Low": 0}

        brand_score = brand_score_map.get(data.get("brand_tier", "C"), 0)
        substitutability_score = substitutability_score_map.get(data.get("substitutability", "Low"), 0)

        result = (
            data.get("product_type"),
            data.get("brand_name"),
            data.get("model_name"),
            data.get("estimated_market_price", 0.0),
            data.get("substitutability"),
            brand_score,
            substitutability_score,
            data.get("reason", "")
        )
        st.session_state.ai_cache[cache_key] = result
        return result

    except Exception as e:
        st.error(f"AI Vision API 调用失败: {e}")
        return None, None, "⚠️ AI调用失败", str(e), 0, 0, 0, "" # 统一返回 None, None 避免后续报错

# --- 核心逻辑 2: 综合打分 (更新了品类分数计算) ---
def analyze_item_with_ai_vision(product_name_input, category_input, my_price, api_key, uploaded_image=None):
    base64_image = encode_image_to_base64(uploaded_image) if uploaded_image else None
    
    # 优先用图片识别，如果没有图片或识别失败，再用文字识别
    if base64_image or product_name_input:
        product_type, brand_name_ai, model_name_ai, estimated_market_price_ai, \
        substitutability_ai, brand_score_ai, substitutability_score_ai, ai_reason = \
            get_ai_product_info_from_image(base64_image, api_key, text_input=product_name_input)
    else:
        # 如果没有图片也没有文字输入，无法分析
        st.error("请提供产品名称或上传图片进行分析。")
        return None

    if product_type is None: # AI 调用失败
        return {
            "总分": 0, "评级建议": "C级-线下处理", "AI品牌评级": "N/A", "AI点评": "AI识别失败",
            "全网参考价": 0, "预估折扣": "0% OFF", "价格备注": "N/A", "链接": "N/A",
            "AI识别品类": "N/A", "AI估算价格": 0, "可替代性": "N/A", "可替代性得分": 0
        }

    # 采用 AI 识别出的信息
    final_product_name = f"{brand_name_ai} {model_name_ai}" if brand_name_ai != "Unknown" else product_type
    market_price = estimated_market_price_ai
    
    # 品类分 (由 AI 评估出的可替代性来修正)
    # 通用品类基础分
    cat_base_score_map = {"电子/家电 (通用)": 20, "知名工具": 15, "特定家电": 10, "家居/户外": 5, "冷门/配件": -10}
    cat_score = cat_base_score_map.get(category_input, 0)
    # 可替代性得分修正：高替代性 +分，低替代性 -分 (这里简单加，如果觉得重复可以调整权重)
    # cat_score += substitutability_score_ai # 暂时不加，避免重复计分，让可替代性单独作为影响因素

    # 价格优势分
    discount_rate = 0
    price_score = 0
    if market_price > 0 and my_price > 0:
        discount_rate = ((market_price - my_price) / market_price) * 100
        if discount_rate >= 70: price_score = 40
        elif discount_rate >= 50: price_score = 30
        elif discount_rate >= 30: price_score = 10
    
    # 价值感知分 (修正: 高客单价更容易吸引眼球)
    value_score = 10 if market_price > 200 else (5 if market_price > 100 else 0)

    # 总分 = 品牌分 + 品类分 + 价格分 + 价值感分 + 可替代性得分
    # 这里的 total_score 体系里，品牌分40，品类分20，价格分40，价值感分10，可替代性10
    # 所以总分可能超过100，需要归一化或者调整权重。
    # 为了简化，直接在原有的基础上，把“可替代性”也算作一个额外加分项（如果是高替代性且低价，反而容易走量）
    
    total_score = brand_score_ai + cat_score + price_score + value_score + substitutability_score_ai
    total_score = min(100, max(0, total_score)) # 确保在0-100之间

    # 评级建议
    if total_score >= 80: suggestion = "S级-引流钩子 (必做广告)"
    elif total_score >= 60: suggestion = "A级-利润核心 (重点上架)"
    elif total_score >= 40: suggestion = "B级-凑单/盲盒 ($10区)"
    else: suggestion = "C级-线下处理 (建议放弃)"

    return {
        "总分": total_score,
        "评级建议": suggestion,
        "AI品牌评级": brand_name_ai,
        "AI点评": ai_reason,
        "全网参考价": market_price,
        "预估折扣": f"{int(discount_rate)}% OFF",
        "价格备注": price_note,
        "链接": "AI估算" if market_price == estimated_market_price_ai else "N/A",
        "AI识别品类": product_type,
        "AI估算价格": estimated_market_price_ai,
        "可替代性": substitutability_ai,
        "可替代性得分": substitutability_score_ai
    }

# --- UI 界面 ---
st.title("👁️ 尾货智能选品雷达 (AI Vision Pro版)")
st.markdown("支持 **AI识图**、**单品交互** 与 **Excel批量处理** 双模式")

# --- 侧边栏配置 ---
with st.sidebar:
    st.header("🔑 配置中心")
    api_key = st.text_input("请输入 OpenAI API Key", type="password", help="使用 gpt-4o 模型，费用较低，但比 gpt-4o-mini 略高。")
    st.markdown("[👉 如何获取 Key?](https://platform.openai.com/api-keys)")
    st.divider()
    st.info("💡 本工具使用 GPT-4o Vision 模型进行图片识别和智能估价。")

if not api_key:
    st.warning("⚠️ 请先在左侧边栏输入 OpenAI API Key 才能启用 AI 识别功能。")

tab1, tab2 = st.tabs(["🖼️ 单品 AI 识图鉴定", "📄 Excel 批量 AI 鉴定"])

# ==========================================
# 模式一：单品交互 (支持图片)
# ==========================================
with tab1:
    col1, col2 = st.columns([1, 1.5])
    with col1:
        st.info("上传图片或输入产品名称，AI将为您识别并估价。")
        uploaded_image = st.file_uploader("📸 上传产品图片", type=["jpg", "jpeg", "png"])
        
        if uploaded_image:
            st.image(uploaded_image, caption="已上传图片", width=200)

        s_name = st.text_input("或输入产品全名 (品牌+型号)", placeholder="例如: Unbranded USB Hub, Dyson V10 Vacuum")
        s_cat = st.selectbox("产品大致品类", ["电子/家电 (通用)", "知名工具", "特定家电", "家居/户外", "冷门/配件"])
        s_price = st.number_input("你的拿货价 ($)", value=30.0)
        s_btn = st.button("🚀 AI 识图 & 估价", type="primary")

    if s_btn:
        if not api_key:
            st.error("请填写 OpenAI API Key。")
        elif not uploaded_image and not s_name:
            st.error("请上传图片或输入产品名称。")
        else:
            with st.spinner("AI 正在分析图片/文字，识别品牌价值并估算市场价..."):
                res = analyze_item_with_ai_vision(s_name, s_cat, s_price, api_key, uploaded_image)
            
            with col2:
                if res:
                    st.markdown(f"### 🎯 综合得分: <span style='color:#FF4B4B;'>{res['总分']}</span>", unsafe_allow_html=True)
                    st.info(f"**决策建议:** {res['评级建议']}")
                    
                    with st.expander("查看详细 AI 分析报告", expanded=True):
                        st.write(f"**💡 AI识别品类:** {res['AI识别品类']}")
                        st.write(f"**🏷️ AI品牌评级:** {res['AI品牌评级']}")
                        st.caption(f"AI点评: {res['AI点评']}")
                        st.write(f"**💰 AI估算市场价:** ${res['AI估算价格']} ({res['预估折扣']})")
                        st.write(f"**🔄 可替代性:** {res['可替代性']} ({res['可替代性得分']}分)")
                        if res['链接'] and res['链接'] != "N/A": st.markdown(f"[🔗 估价来源]({res['链接']})")
                else:
                    st.error("分析失败，请检查输入和 API Key。")

# ==========================================
# 模式二：批量处理 (仅支持文字输入)
# ==========================================
with tab2:
    st.markdown("### 📥 Excel 批量 AI 选品 (仅限文字)")
    st.markdown("批量模式暂不支持图片上传。请确保 Excel 表格包含【产品全名】字段，AI将根据名称进行分析。")
    
    # 模板下载
    sample_data = pd.DataFrame({
        "产品全名": ["Sony WH-1000XM5", "Unbranded USB-C Hub", "Dyson Airwrap", "Generic White T-Shirt"],
        "产品品类": ["电子/家电 (通用)", "电子/家电 (通用)", "电子/家电 (通用)", "家居/户外"],
        "拟售价": [150, 5, 200, 3]
    })
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        sample_data.to_excel(writer, index=False)
    st.download_button("📥 下载 Excel 模版", buffer, "AI选品模版.xlsx")

    uploaded_file = st.file_uploader("上传清单", type=["xlsx"], key="batch_upload")

    if uploaded_file and api_key:
        if st.button("⚡ 开始批量 AI 分析", key="batch_analyze_btn"):
            df = pd.read_excel(uploaded_file)
            results = []
            bar = st.progress(0)
            status = st.empty()
            
            # 检查关键列
            required_cols = ["产品全名", "产品品类", "拟售价"]
            if not all(col in df.columns for col in required_cols):
                st.error(f"❌ 批量文件列名不匹配！请确保包含: {required_cols}")
                st.stop()

            for i, row in df.iterrows():
                status.text(f"正在 AI 分析第 {i+1}/{len(df)} 个: {row['产品全名']}...")
                bar.progress((i + 1) / len(df))
                
                # 批量模式只用文字输入给AI
                res = analyze_item_with_ai_vision(
                    row['产品全名'], 
                    row.get('产品品类', '电子/家电 (通用)'), 
                    float(row['拟售价']), 
                    api_key,
                    uploaded_image=None # 批量模式不传图片
                )
                
                combined = row.to_dict()
                if res: # 确保分析成功
                    combined.update({
                        "总分": res['总分'],
                        "评级建议": res['评级建议'],
                        "AI品牌评级": res['AI品牌评级'],
                        "AI点评": res['AI点评'],
                        "AI识别品类": res['AI识别品类'],
                        "AI估算市场价": res['AI估算价格'],
                        "可替代性": res['可替代性'],
                        "可替代性得分": res['可替代性得分'],
                        "你的拟售价": float(row['拟售价']), # 方便对比
                        "预估折扣": res['预估折扣'],
                        "价格备注": res['价格备注']
                    })
                else: # 失败时填充默认值
                    combined.update({
                        "总分": 0, "评级建议": "失败", "AI品牌评级": "N/A", "AI点评": "API调用失败",
                        "AI识别品类": "N/A", "AI估算市场价": 0, "可替代性": "N/A", "可替代性得分": 0,
                        "你的拟售价": float(row['拟售价']),
                        "预估折扣": "0% OFF", "价格备注": "失败"
                    })
                
                results.append(combined)
                time.sleep(1.0) # 避免触发 API 速率限制

            st.success("✅ 批量 AI 分析完成！")
            final_df = pd.DataFrame(results)
            st.dataframe(final_df)
            
            # 导出
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
                final_df.to_excel(writer, index=False)
            st.download_button("📥 下载 AI 详细分析报告", out, "AI选品批量结果.xlsx")
