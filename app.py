# app.py — AI 文案生成（小红书为主，多平台协同）— 批量 & 排期（移动端优化 + Seattle + 署名）
# 运行：
#   pip install -r requirements.txt
#   streamlit run app.py
# 说明：
#   - 无 OPENAI/YELP Key 也能运行（模板生成 + 离线地域词）
#   - 有 Key 将自动启用 LLM 与 Yelp 热词增强
#   - 深色主题在 .streamlit/config.toml 中配置

import os
import json
import random
import datetime as dt
from typing import List, Dict, Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# === 外部数据源开关（无 Key 则退化到离线模板） ===
USE_OPENAI = bool(os.getenv("OPENAI_API_KEY"))
USE_YELP   = bool(os.getenv("YELP_API_KEY"))

# Google Trends（pytrends，无需 Key，联网可用）
try:
    from pytrends.request import TrendReq
    HAS_PYTRENDS = True
except Exception:
    HAS_PYTRENDS = False

# ====== 基础配置 ======
PLATFORMS = ["小红书", "Instagram", "TikTok", "Facebook", "Nextdoor", "Yelp", "X"]
INDUSTRIES = [
    "餐饮 / 美食", "美业（美甲/美容/医美）", "教育培训",
    "零售门店", "健身/瑜伽", "旅游/本地玩乐", "其他"
]
TONES = ["专业可信", "亲切生活化", "潮酷年轻", "高端极简", "幽默风趣"]
LANG_CHOICES = ["中文", "英文", "中英双语"]

# ========== 页面配置（首次自动展开，保留官方收起/展开按钮） ==========
st.set_page_config(
    page_title="AI 文案生成（批量）",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"   # 首次进入自动展开
)

st.title("🧠 AI 文案生成（批量 & 排期）")
st.caption("最少问题 → 地区热词 → 多平台爆款文案（可批量） → 平台模板导出 → 内容排期日历")

# 地域离线洞察（可按需扩充）
REGION_FACTS = {
    "San Francisco": {
        "neighborhoods": ["Sunset", "Richmond", "SoMa", "Mission", "Financial District", "Pacific Heights", "Noriega"],
        "audience": ["留学生", "科技从业者", "年轻白领", "家庭客"],
        "seasonal": ["樱花季金门公园野餐", "夏末餐饮节", "湾区开学季"],
        "food_tags": ["湾区美食", "旧金山中餐", "Richmond美食", "Noriega好店"],
        "events": ["樱花节", "SF Pride", "Outside Lands", "Chinese New Year Parade"],
        "posting_hours": {"工作日": ["12:00-13:30","19:30-21:30"], "周末": ["10:30-12:00","20:00-22:00"]}
    },
    "Los Angeles": {
        "neighborhoods": ["SGV", "Monterey Park", "Arcadia", "Koreatown", "DTLA", "Santa Monica"],
        "audience": ["留学生", "观光游客", "本地家庭", "内容创作者"],
        "seasonal": ["春假出游季", "暑期打卡", "感恩节购物季"],
        "food_tags": ["洛杉矶美食", "SGV中餐", "LA吃货", "打卡餐厅"],
        "events": ["LA Food Fest", "Anime Expo", "Rose Parade"],
        "posting_hours": {"工作日": ["12:00-14:00","20:00-22:00"], "周末": ["11:00-13:00","19:00-22:00"]}
    },
    "New York": {
        "neighborhoods": ["Flushing", "Chinatown", "Brooklyn", "Midtown", "Queens"],
        "audience": ["上班族", "游客", "留学生"],
        "seasonal": ["春季赏樱", "假日购物季"],
        "food_tags": ["纽约美食", "法拉盛吃喝玩乐"],
        "events": ["NYC Restaurant Week", "NYC Marathon", "Times Square NYE"],
        "posting_hours": {"工作日": ["12:00-14:00","19:00-22:00"], "周末": ["10:30-12:30","20:00-23:00"]}
    },
    # === 新增：Seattle ===
    "Seattle": {
        "neighborhoods": ["Bellevue", "Downtown", "Capitol Hill", "University District", "Chinatown"],
        "audience": ["留学生", "科技从业者", "本地家庭", "新移民"],
        "seasonal": ["樱花季 UW 校园", "夏季户外节", "感恩节火鸡节"],
        "food_tags": ["西雅图美食", "Bellevue中餐", "UW周边吃喝玩乐"],
        "events": ["Seattle Restaurant Week", "Bumbershoot Music Festival", "Seattle Film Festival"],
        "posting_hours": {"工作日": ["11:30-13:30","19:00-21:30"], "周末": ["10:00-12:30","19:00-22:00"]}
    }
}

BASE_HASHTAGS = {
    "小红书": ["探店", "种草", "生活方式", "留学生", "北美生活", "湾区"],
    "Instagram": ["foodie", "instafood", "madeinLA", "bayarea", "vibes", "reels"],
    "TikTok": ["fyp", "tiktokfood", "tiktokmademebuyit", "bayarea", "losangeles"],
    "Facebook": ["localbusiness", "community", "familyfriendly"],
    "Nextdoor": ["local", "neighbors", "recommendation"],
    "Yelp": ["newintown", "yelpelite", "foodphotography"],
    "X": ["NowInSF", "LAeats", "BayArea", "FoodTok"]
}

INDUSTRY_HASHTAGS = {
    "餐饮 / 美食": ["中餐", "川菜", "火锅", "烘焙", "甜品", "美食推荐"],
    "美业（美甲/美容/医美）": ["美甲", "美睫", "护肤", "Spa", "医美"],
    "教育培训": ["补习", "托福", "少儿编程", "周末课堂"],
    "零售门店": ["开箱", "精选好物", "本地小店"],
    "健身/瑜伽": ["健身打卡", "私教", "瑜伽日常"],
    "旅游/本地玩乐": ["周末去哪儿", "亲子游", "城市漫步"],
    "其他": []
}

def combine_hashtags(platform: str, industry: str, city: str) -> List[str]:
    base = BASE_HASHTAGS.get(platform, [])[:4]
    ind  = INDUSTRY_HASHTAGS.get(industry, [])[:4]
    city_tag = [city.replace(" ", ""), city]
    tags = list(dict.fromkeys(base + ind + city_tag))
    return [f"#{t}" if not t.startswith("#") else t for t in tags]

# ==== Google Trends（可选） ====
def google_trends_hotwords(city: str, kw_seed: List[str]) -> List[str]:
    if not HAS_PYTRENDS:
        return []
    try:
        pytrends = TrendReq(hl='en-US', tz=360)
        pytrends.build_payload(kw_seed, timeframe='today 3-m', geo='US')
        related = pytrends.related_queries()
        hot = []
        for _, v in related.items():
            if v and 'top' in v and isinstance(v['top'], pd.DataFrame):
                hot += v['top']['query'].head(5).tolist()
        return list(dict.fromkeys(hot))[:15]
    except Exception:
        return []

# ==== Yelp 热词（可选） ====
def yelp_hotwords(city: str, category: str="chinese") -> List[str]:
    if not USE_YELP:
        return []
    try:
        from yelpapi import YelpAPI
        yp = YelpAPI(os.getenv("YELP_API_KEY"))
        resp = yp.search_query(location=city, categories=category, sort_by='rating', limit=20)
        names = [b['name'] for b in resp.get('businesses', [])]
        kw = []
        for n in names:
            kw += n.split()
        return list(dict.fromkeys([w.strip("#").lower() for w in kw if len(w) > 2]))[:20]
    except Exception:
        return []

# ==== 热词融合 ====
def build_hotwords(city: str, industry: str) -> List[str]:
    facts = REGION_FACTS.get(city, {})
    seeds = []
    seeds += facts.get("food_tags", []) if ("餐" in industry or "美食" in industry) else []
    seeds += facts.get("neighborhoods", [])
    seeds += facts.get("events", [])
    seeds += INDUSTRY_HASHTAGS.get(industry, [])

    gt = google_trends_hotwords(city, kw_seed=list(set([industry, city])))
    yp = yelp_hotwords(city, category="chinese" if ("餐" in industry or "美食" in industry) else "beautysvc")

    words = list(dict.fromkeys(seeds + gt + yp))
    words = [w.strip().replace(" ", "") for w in words if isinstance(w, str) and len(w.strip()) > 1]
    return words[:30]

# ==== 文案生成（LLM 可选；无 Key 则用模板） ====
def llm_copy(platform: str, lang: str, brief: Dict[str, Any], hotwords: List[str]) -> Dict[str, Any]:
    city = brief["city"]
    industry = brief["industry"]
    tone = brief["tone"]
    offer = brief.get("offer", "")
    usp = brief.get("usp", "")
    brand = brief.get("brand", "")
    hours = REGION_FACTS.get(city, {}).get("posting_hours", {})
    hashtags = combine_hashtags(platform, industry, city)
    extra_kw = random.sample(hotwords, k=min(5, len(hotwords))) if hotwords else []

    # 无 OpenAI → 模板
    if not USE_OPENAI:
        title = f"{brand}｜{city} {industry} {random.choice(['今日上新','限时福利','本地口碑','人气爆款'])}"
        if platform == "Nextdoor":
            body = f"{brand} 位于 {city} 社区，{usp}。本周{offer or '欢迎邻居来店体验'}。如果您来过，欢迎在社区里分享建议，我们会认真改进。"
        elif platform == "Yelp":
            body = f"真实体验分享：{brand}（{city}）。本周亮点：{usp}。{offer or '欢迎预订/Walk-in'}。若有任何建议，欢迎在Yelp私信或评论，我们会及时回复。"
        else:
            body = f"{usp} {offer} {city} 本地{industry}，{tone}表达。关键词：{', '.join(extra_kw)}。"
        hooks = [
            f"开头3秒：{city}{industry}为什么都来这里？",
            f"你不知道的{brand}隐藏菜单",
            f"{city}人都在搜：{', '.join(extra_kw[:3])}"
        ]
        shotlist = ["门头与街景（5秒）", "爆款产品特写（8秒）", "制作/服务过程（10秒）", "顾客反馈（5秒）", "结尾优惠+地址（3秒）"]
        return {
            "title": title,
            "body": body,
            "hashtags": hashtags + [f"#{w}" for w in extra_kw],
            "shotlist": shotlist,
            "hooks": hooks,
            "cta": brief.get("cta", "现在预约/下单，出示本帖享优惠"),
            "post_time": hours or {"建议": "工作日午餐前后或晚间，周末上午或晚间（本地峰值）"}
        }

    # 有 OpenAI → 走 LLM
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    sys_prompt = f"""
你是北美本地化社媒创意总监擅长餐饮运营推广精通顾客消费心理和平台流量规则。平台：{platform}；城市：{city}；行业：{industry}；风格：{tone}；语言：{lang}
输出：1) 标题；2) 正文（平台最佳长度）；3) ≤10个hashtags（含城市+行业+热词）；
4) ≥3条3秒Hook；5) 5-7镜头Shotlist；6) 明确CTA；7) 发布时间建议。
热词：{', '.join(extra_kw)}；USP：{usp}；优惠：{offer}。
各平台口吻需差异化：小红书生活化、TikTok抓眼、IG视觉/话题、Nextdoor社区口吻、Yelp真实体验。
"""
    user_prompt = json.dumps(brief, ensure_ascii=False)
    rsp = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[{"role":"system","content":sys_prompt},{"role":"user","content":user_prompt}],
        temperature=0.8,
    )
    text = rsp.choices[0].message.content.strip()
    return {
        "title": f"{brand} - {platform}",
        "body": text,
        "hashtags": hashtags + [f"#{w}" for w in extra_kw],
        "shotlist": [],
        "hooks": [],
        "cta": brief.get("cta", "现在预约/下单"),
        "post_time": hours or {}
    }

# ==== 批量排期 ====
def pick_post_datetime(city: str, day: dt.date) -> dt.datetime:
    info = REGION_FACTS.get(city, {}).get("posting_hours", {})
    wk = "周末" if day.weekday() >= 5 else "工作日"
    slots = info.get(wk) or ["12:00-13:30","19:00-21:00"]
    hhmm = random.choice(slots).split("-")[0]
    hh, mm = hhmm.split(":")
    return dt.datetime.combine(day, dt.time(int(hh), int(mm)))

def platform_export_row(p: str, r: Dict[str, Any]) -> Dict[str, Any]:
    if p == "小红书":
        return {"Title": r["title"], "Body": r["body"], "Tags": " ".join(r["hashtags"]), "CTA": r["cta"],
                "Shotlist": " / ".join(r["shotlist"]), "Hooks": " | ".join(r["hooks"])}
    if p == "Instagram":
        return {"Caption": r["body"], "Hashtags": " ".join(r["hashtags"]), "AltText": "Brand/product", "CTA": r["cta"]}
    if p == "TikTok":
        return {"Caption": r["body"], "Hashtags": " ".join(r["hashtags"]), "CTA": r["cta"]}
    if p == "Facebook":
        return {"PostText": r["body"], "CTA": r["cta"]}
    if p == "Nextdoor":
        return {"NeighborhoodPost": r["body"], "CTA": r["cta"]}
    if p == "Yelp":
        return {"OwnerUpdate": r["body"][:1000], "Note": "保持真实体验口吻", "CTA": r["cta"]}
    if p == "X":
        return {"Tweet": r["body"][:260], "Hashtags": " ".join(r["hashtags"][:4])}
    return {"Text": r["body"]}

# ==== UI ====
with st.sidebar:
    st.header("1) 基础信息（最少必填）")
    brand    = st.text_input("品牌/门店名", placeholder="如：老李家川菜")
    industry = st.selectbox("行业", INDUSTRIES, index=0)
    city     = st.selectbox("城市/地区", list(REGION_FACTS.keys()), index=0)
    usp      = st.text_input("差异化卖点（USP）", placeholder="如：真材实料/24小时出餐/师资强/连锁直营")
    offer    = st.text_input("优惠/活动（可选）", placeholder="如：本周新客9折；工作日午市套餐$12.99")
    cta      = st.text_input("CTA 号召语", value="立即预约/下单，出示本帖享受活动")
    tone     = st.selectbox("文案风格", TONES, index=1)
    lang     = st.selectbox("语言", LANG_CHOICES, index=0)
    targets  = st.multiselect("平台选择", PLATFORMS, default=["小红书","Instagram","TikTok"])

    st.header("2) 批量生成")
    mode       = st.radio("模式", ["单次生成", "批量按天"], horizontal=True)
    start_date = st.date_input("开始日期", value=dt.date.today())
    days       = st.number_input("天数（批量）", min_value=1, max_value=60, value=30)
    per_day    = st.number_input("每日条数（每个平台）", min_value=1, max_value=3, value=1)

    submit = st.button("🚀 生成文案 / 批量排期", type="primary", use_container_width=True)

if submit:
    if not brand or not industry or not city:
        st.error("请至少填写：品牌、行业、城市。")
        st.stop()

    with st.spinner("正在收集地区热词 & 生成内容…"):
        hotwords = build_hotwords(city, industry)
        brief = {
            "brand": brand, "industry": industry, "city": city, "tone": tone,
            "usp": usp, "offer": offer, "cta": cta, "lang": lang,
            "date": dt.date.today().isoformat(), "platforms": targets
        }

        rows, calendar_rows = [], []

        def iter_schedule():
            if mode == "单次生成":
                yield start_date
            else:
                for i in range(int(days)):
                    yield start_date + dt.timedelta(days=int(i))

        for d in iter_schedule():
            for p in targets:
                for _ in range(int(per_day)):
                    r = llm_copy(p, lang, brief, hotwords)
                    r["platform"] = p
                    dt_post = pick_post_datetime(city, d)

                    rows.append({
                        "日期": d.isoformat(),
                        "发布时间": dt_post.strftime("%Y-%m-%d %H:%M"),
                        "平台": p,
                        "标题": r["title"],
                        "正文": r["body"],
                        "话题": " ".join(r["hashtags"]),
                        "拍摄分镜": " / ".join(r["shotlist"]),
                        "视频Hook": " | ".join(r["hooks"]),
                        "CTA": r["cta"],
                        "城市": city,
                        "品牌": brand,
                        "行业": industry
                    })
                    calendar_rows.append({
                        "Date": d.isoformat(),
                        "Time": dt_post.strftime("%H:%M"),
                        "Platform": p,
                        "City": city,
                        "Brand": brand,
                        "Title": r["title"],
                        "AssetNeeds": "Photo/Video, Logo, Address Tag",
                        "FilenameSlug": f"{brand}_{city}_{p}_{d.strftime('%m%d')}".replace(" ", ""),
                        "Hashtags": " ".join(r["hashtags"])
                    })

        df     = pd.DataFrame(rows)
        cal_df = pd.DataFrame(calendar_rows)

    st.success("生成完成 ✅")
    st.subheader("🔎 地区热词（合成）")
    st.write(", ".join(hotwords) if hotwords else "（未能联网获取，将根据离线词库生成）")

    st.subheader("📆 排期日历（预览）")
    st.dataframe(cal_df.head(20), use_container_width=True)

    st.subheader("📦 多平台文案（预览）")
    st.dataframe(df.head(20), use_container_width=True)

    # 平台模板导出
    platform_csvs = {}
    for p in targets:
        sub = df[df["平台"] == p]
        mapped = [platform_export_row(p, {
            "title": row["标题"],
            "body": row["正文"],
            "hashtags": row["话题"].split(),
            "shotlist": row["拍摄分镜"].split(" / ") if row["拍摄分镜"] else [],
            "hooks": row["视频Hook"].split(" | ") if row["视频Hook"] else [],
            "cta": row["CTA"]
        }) for _, row in sub.iterrows()]
        p_df = pd.DataFrame(mapped)
        platform_csvs[p] = p_df

    # 导出
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    cal_bytes = cal_df.to_csv(index=False).encode("utf-8")
    st.download_button("下载 CSV（所有平台合并）", csv_bytes, file_name=f"{brand}_{city}_all_posts.csv")
    st.download_button("下载 CSV（内容排期日历）", cal_bytes, file_name=f"{brand}_{city}_content_calendar.csv")

    st.subheader("🧩 平台专用导出模板")
    for p, p_df in platform_csvs.items():
        st.download_button(f"下载 {p} CSV 模板", p_df.to_csv(index=False).encode("utf-8"),
                           file_name=f"{brand}_{city}_{p}_template.csv")

    # TXT 合集
    all_txt = []
    for _, row in df.iterrows():
        all_txt.append(f"【{row['平台']}】{row['标题']}\n{row['正文']}\n话题：{row['话题']}\nCTA：{row['CTA']}\n发布时间：{row['发布时间']}\n")
    all_txt_str = "\n\n".join(all_txt)
    st.download_button("下载 TXT（全文案合集）", all_txt_str.encode("utf-8"),
                       file_name=f"{brand}_{city}_all_copies.txt")

    # ZIP 打包
    from io import BytesIO
    import zipfile
    mem_zip = BytesIO()
    with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{brand}_{city}_all_posts.csv", csv_bytes)
        zf.writestr(f"{brand}_{city}_content_calendar.csv", cal_bytes)
        zf.writestr(f"{brand}_{city}_all_copies.txt", all_txt_str.encode("utf-8"))
        for p, p_df in platform_csvs.items():
            zf.writestr(f"{brand}_{city}_{p}_template.csv", p_df.to_csv(index=False).encode("utf-8"))
    mem_zip.seek(0)
    st.download_button("📦 下载ZIP（全量打包）", mem_zip.read(), file_name=f"{brand}_{city}_content_pack.zip")

# ========== 侧边栏署名（LinkedIn） ==========
st.sidebar.markdown(
    """
    <div style='text-align:center; padding-top: 2rem;'>
        👨‍💻 Build by <b>c8geek</b>
        <a href='https://www.linkedin.com/in/lingyu-maxwell-lai' target='_blank' title='LinkedIn'>
            <img src='https://cdn.jsdelivr.net/gh/simple-icons/simple-icons/icons/linkedin.svg'
                 width='18' style='vertical-align:middle; margin-left:6px;'/>
        </a>
    </div>
    """,
    unsafe_allow_html=True
)
