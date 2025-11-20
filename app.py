import streamlit as st
import pandas as pd
import re
import time
import io
import openai
import json
import base64
import requests

# --- 页面配置 ---
st.set_page_config(page_title="尾货智能选品雷达 (全品类版)", page_icon="📊", layout="wide")

# --- 全局缓存 ---
if 'ai_cache' not in st.session_state:
    st.session_state.ai_cache = {}

# --- 辅助函数：图片编码 ---
def encode_image_to_base64(uploaded_file):
    if uploaded_file is not None:
        return base64.b64encode(uploaded_file.read()).decode("utf-8")
    return None

# --- 核心逻辑 1: 亚马逊数据获取 (RapidAPI) ---
def search_market_price_rapidapi(product_query, rapidapi_key):
    """
    调用 RapidAPI 获取：价格、月销量、链接
    """
    if not rapidapi_key:
        return 0, None, "⚠️ 未配置RapidAPI", "N/A"

    url = "https://real-time-amazon-data.p.rapidapi.com/search"
    querystring = {"query": product_query, "page": "1", "country": "US", "sort_by": "RELEVANCE"}
    
    headers = {
        "X-RapidAPI-Key": rapidapi_key,
        "X-RapidAPI-Host": "real-time-amazon-data.p.rapidapi.com"
    }

    try:
        response = requests.get(url, headers=headers, params=querystring)
        data = response.json()
        
        if data.get("status") == "OK" and data.get("data") and data.get("data", {}).get("products"):
            top_product = data["data"]["products"][0]
            
            # 1. 提取价格
            price = top_product.get("product_price")
            clean_price = 0
            if price:
                try:
                    clean_price = float(str(price).replace('$', '').replace(',', ''))
                except: pass
            
            # 2. 提取月销量
            sales_volume = top_product.get("sales_volume", "暂无数据")
            
            # 3. 链接
            product_url = top_product.get("product_url")
            
            return clean_price, product_url, "✅ Amazon API数据", sales_volume
        else:
            return 0, None, "❌ API未搜到", "N/A"

    except Exception as e:
        return 0, None, f"API错误: {str(e)}", "N/A"

# --- 核心逻辑 2: AI Vision 识别 & 估算 ---
def get_ai_product_info(base64_image, api_key, text_input=None):
    if not api_key:
        return None 

    client = openai.OpenAI(api_key=api_key)
    
    messages_content = []
    if base64_image:
        messages_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}", "detail": "low"}
        })

    prompt = f"""
    You are a US liquidation expert. Analyze the product (Image/Text: "{text_input}").
    
    Tasks:
    1. **Identify:** Product Type, Brand, Model.
    2. **Valuation:** Estimate typical Amazon Price ($).
    3. **Sales Velocity:** Estimate monthly sales volume on Amazon (e.g., "5000+ units", "500+ units", "Low").
    4. **Substitutability:** High (Generic) / Medium / Low (Unique).
    5. **Brand Tier:** S (Luxury/Top), A (Known), B (Budget), C (Unknown).
    6. **Reason:** Why did you give this tier? (in Chinese).

    Output JSON:
    {{
        "product_type": "...",
        "brand_name": "...",
        "model_name": "...",
        "estimated_price": 0.0,
        "estimated_sales": "...",
        "substitutability": "High/Medium/Low",
        "brand_tier": "S/A/B/C",
        "reason": "..."
    }}
    """
    messages_content.append({"type": "text", "text": prompt})

    cache_key = (base64_image[:50] if base64_image else "") + (text_input or "") 
    if cache_key in st.session_state.ai_cache:
        return st.session_state.ai_cache[cache_key]

    try:
        response = client.chat.completions.create(
            model="gpt-4o", 
            messages=[{"role": "user", "content": messages_content}],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        data = json.loads(response.choices[0].message.content)
        st.session_state.ai_cache[cache_key] = data
        return data
    except Exception as e:
        st.error(f"AI Error: {e}")
        return None

# --- 核心逻辑 3: 综合分析与打分 ---
def analyze_item_complete(product_name, category, my_price, openai_key, rapidapi_key, image=None):
    
    base64_img = encode_image_to_base64(image)
    
    # 1. AI 识别
    ai_data = get_ai_product_info(base64_img, openai_key, product_name)
    if not ai_data:
        return None

    # 2. 获取市场数据
    api_price, api_link, price_source, api_sales = search_market_price_rapidapi(
        f"{ai_data['brand_name']} {ai_data['model_name'] or ai_data['product_type']}", 
        rapidapi_key
    )

    final_price = api_price if api_price > 0 else ai_data['estimated_price']
    final_sales = api_sales if (api_sales and api_sales != "N/A") else f"AI预估: {ai_data['estimated_sales']}"
    link = api_link if api_link else "N/A"

    # ---------------------------------------------------
    # 🎯 评分规则引擎 (已更新虚拟产品逻辑)
    # ---------------------------------------------------
    score_breakdown = {}
    
    # A. 品牌分 (40分)
    brand_map = {"S": 40, "A": 30, "B": 15, "C": 0}
    brand_score = brand_map.get(ai_data['brand_tier'], 0)
    score_breakdown['品牌分'] = {
        "score": brand_score, 
        "max": 40, 
        "desc": f"等级: {ai_data['brand_tier']}级 ({ai_data['brand_name']})"
    }

    # B. 品类热度分 (20分) - 【此处已新增】
    cat_map = {
        "电子/家电 (通用)": 20, 
        "知名工具": 15, 
        "特定家电": 10, 
        "虚拟/数字产品 (激活码/卡)": 5, # <--- 新增逻辑
        "家居/户外": 5, 
        "冷门/配件": -10
    }
    cat_score = cat_map.get(category, 0)
    score_breakdown['品类分'] = {
        "score": cat_score, 
        "max": 20, 
        "desc": category
    }

    # C. 价格优势分 (40分)
    discount_rate = 0
    price_score = 0
    if final_price > 0 and my_price > 0:
        discount_rate = ((final_price - my_price) / final_price) * 100
        if discount_rate >= 70: price_score = 40
        elif discount_rate >= 50: price_score = 30
        elif discount_rate >= 30: price_score = 10
    
    score_breakdown['价格优势'] = {
        "score": price_score, 
        "max": 40, 
        "desc": f"折扣力度: {int(discount_rate)}% OFF"
    }

    # D. 附加分：价值感 (10分)
    val_score = 10 if final_price > 100 else 0
    score_breakdown['高价值加权'] = {
        "score": val_score, 
        "max": 10, 
        "desc": "市场价 > $100" if val_score > 0 else "低客单价"
    }
    
    # 计算总分
    total_score = min(100, max(0, brand_score + cat_score + price_score + val_score))

    # 评级建议
    if total_score >= 80: suggestion = "S级-引流钩子 (必做广告)"
    elif total_score >= 60: suggestion = "A级-利润核心 (重点上架)"
    elif total_score >= 40: suggestion = "B级-凑单/盲盒 ($10区)"
    else: suggestion = "C级-线下处理 (建议放弃)"

    return {
        "总分": total_score,
        "评级建议": suggestion,
        "商品信息": {
            "全名": f"{ai_data['brand_name']} {ai_data['model_name']}",
            "品类": ai_data['product_type'],
            "AI点评": ai_data['reason']
        },
        "市场数据": {
            "参考价": final_price,
            "价格来源": price_source,
            "月销量": final_sales,
            "链接": link,
            "预估折扣": f"{int(discount_rate)}%"
        },
        "评分细则": score_breakdown,
        "raw_ai": ai_data
    }

# --- UI 界面 ---
st.title("📊 尾货智能选品雷达 (全品类版)")

with st.sidebar:
    st.header("🔑 配置中心")
    openai_key = st.text_input("1. OpenAI API Key", type="password")
    rapidapi_key = st.text_input("2. RapidAPI Key (选填)", type="password", help="用于获取精准月销量和价格")
    st.caption("RapidAPI: Real-Time Amazon Data")
    st.divider()

if not openai_key:
    st.warning("请先输入 OpenAI API Key")
    st.stop()

tab1, tab2 = st.tabs(["🔍 单品透视", "📄 批量报表"])

# --- 单品模式 ---
with tab1:
    c1, c2 = st.columns([1, 1.5])
    with c1:
        img = st.file_uploader("上传图片", type=["jpg","png"])
        txt = st.text_input("产品名称", placeholder="例如: Windows 10 Pro Key")
        
        # --- UI 更新：新增选项 ---
        cat = st.selectbox("品类", [
            "电子/家电 (通用)", 
            "知名工具", 
            "特定家电", 
            "虚拟/数字产品 (激活码/卡)", # <--- 新增选项
            "家居/户外", 
            "冷门/配件"
        ])
        
        price = st.number_input("拿货价 ($)", value=9.90)
        btn = st.button("🚀 深度分析")

    if btn:
        with st.spinner("AI 正在识别 + 爬取亚马逊销量数据..."):
            res = analyze_item_complete(txt, cat, price, openai_key, rapidapi_key, img)
        
        if res:
            with c2:
                # 1. 头部大分
                score_color = "#ff4b4b"
                if res['总分'] >= 80: score_color = "#09ab3b"
                elif res['总分'] >= 60: score_color = "#ffbd45"

                st.markdown(f"""
                <div style="padding:20px; border-radius:10px; background-color:#f0f2f6; text-align:center; border: 2px solid {score_color}">
                    <h3 style="margin:0; color:gray">选品综合得分</h3>
                    <h1 style="font-size:64px; margin:0; color:{score_color}">{res['总分']}</h1>
                    <h4 style="margin:0; color:#333">{res['评级建议']}</h4>
                </div>
                """, unsafe_allow_html=True)

                # 2. 市场数据
                st.markdown("### 📈 市场表现 (过去一个月)")
                m1, m2, m3 = st.columns(3)
                m1.metric("月销量", res['市场数据']['月销量'])
                m2.metric("市场价", f"${res['市场数据']['参考价']}", delta=res['市场数据']['价格来源'])
                m3.metric("利润空间", res['市场数据']['预估折扣'], delta="OFF")
                
                if res['市场数据']['链接'] != "N/A":
                    st.markdown(f"[🔗 点击跳转 Amazon 查看详情]({res['市场数据']['链接']})")

                # 3. 评分细则
                st.markdown("### 💯 评分规则细则")
                rules = res['评分细则']
                
                b = rules['品牌分']
                st.progress(b['score']/40, text=f"品牌力: {b['score']}/40 分 — {b['desc']}")
                
                p = rules['价格优势']
                st.progress(p['score']/40, text=f"价格优势: {p['score']}/40 分 — {p['desc']}")
                
                c = rules['品类分']
                c_val = max(0, c['score'])
                st.progress(c_val/20, text=f"品类热度: {c['score']}/20 分 — {c['desc']}")
                
                v = rules['高价值加权']
                st.progress(v['score']/10, text=f"高价值加权: {v['score']}/10 分 — {v['desc']}")

                # 4. AI 点评
                st.info(f"**💡 专家点评:** {res['商品信息']['AI点评']}")

# --- 批量模式 ---
with tab2:
    st.info("批量模式已支持【虚拟/数字产品】。")
    
    df_template = pd.DataFrame({
        "产品全名": ["Ninja AF101", "Windows 10 Home Key"], 
        "产品品类": ["特定家电", "虚拟/数字产品 (激活码/卡)"], 
        "拟售价": [40, 9.9]
    })
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df_template.to_excel(writer, index=False)
    st.download_button("📥 下载模板", buffer, "template.xlsx")

    up_file = st.file_uploader("上传 Excel", type=["xlsx"])
    
    if up_file and st.button("⚡ 开始批量跑数"):
        df = pd.read_excel(up_file)
        results = []
        bar = st.progress(0)
        
        for i, row in df.iterrows():
            bar.progress((i+1)/len(df))
            r = analyze_item_complete(
                row['产品全名'], 
                row.get('产品品类', '电子/家电 (通用)'), 
                float(row['拟售价']), 
                openai_key, 
                rapidapi_key
            )
            
            if r:
                flat_res = row.to_dict()
                flat_res.update({
                    "综合得分": r['总分'],
                    "评级": r['评级建议'],
                    "品牌": r['商品信息']['全名'],
                    "市场价": r['市场数据']['参考价'],
                    "月销量": r['市场数据']['月销量'],
                    "折扣": r['市场数据']['预估折扣'],
                    "品牌分": r['评分细则']['品牌分']['score'],
                    "价格分": r['评分细则']['价格优势']['score']
                })
                results.append(flat_res)
            time.sleep(1)

        final_df = pd.DataFrame(results)
        st.dataframe(final_df)
        
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine='xlsxwriter') as writer:
            final_df.to_excel(writer, index=False)
        st.download_button("📥 下载完整报表", out, "销量分析报告.xlsx")
