"""Spot classifier: auto-categorize spots based on name keywords and rules."""

# Category keyword mapping
CATEGORY_KEYWORDS = {
    "自然景观": [
        "天池", "峡谷", "瀑布", "溶洞", "湿地", "国家公园",
        "风景区", "溪流", "天坑", "石林", "丹霞",
        "山风景区", "山旅游区", "山生态",
        "湖景区", "湖旅游",
        "峰景区", "峰旅游区",
    ],
    "人文历史": [
        "古", "寺", "庙", "祠", "观", "院", "陵", "墓", "故居",
        "古城", "古镇", "古村", "遗址", "博物馆", "纪念馆", "书院",
        "王府", "牌坊", "碑", "塔", "阁", "衙", "衙门", "楼", "殿",
        "文化", "革命", "红色", "红军", "纪念", "孔子", "李白", "屈原",
        "关陵", "关羽", "张居正", "曾国藩", "明显陵", "炎帝", "神农",
    ],
    "主题乐园": [
        "乐园", "游乐园", "动物园", "植物园", "海洋世界", "蜡像",
        "冒险", "勇敢者", "蹦床", "飞天", "丛林", "城堡",
        "儿童", "亲子", "松鼠", "大马戏", "马戏", "森林动物园", "野生动物园",
    ],
    "温泉康养": [
        "温泉", "养生", "汤泉", "汤池", "spa", "SPA", "理疗", "泡汤",
    ],
    "户外运动": [
        "漂流", "滑雪", "帆船", "皮划艇", "攀岩", "徒步",
        "露营", "营地", "滑道", "索道", "玻璃", "VR",
        "帆船", "赛艇", "水上", "潜水",
    ],
    "演艺演出": [
        "剧场", "演出", "实景演出", "秀", "汉秀", "编钟",
        "寻梦", "不夜城", "光影", "剧",
    ],
    "休闲农业": [
        "花海", "农庄", "采摘", "田园", "茶谷", "玫瑰园",
        "樱花园", "荷花园", "牡丹园", "梅园", "郁金香",
        "生态园", "牧场", "稻田", "桔园", "果园", "庄园", "农园",
    ],
    "城市娱乐": [
        "影城", "VR", "台球", "运动", "蹦床", "飞车",
        "探索中心", "科技馆", "观光厅", "观光", "氦气球",
    ],
}

# Sub-category mapping
SUB_CATEGORY_KEYWORDS = {
    "漂流": ["漂流"],
    "滑雪": ["滑雪"],
    "溶洞": ["溶洞", "洞"],
    "温泉": ["温泉"],
    "动物园": ["动物园", "动物", "野生动物"],
    "植物园": ["植物园"],
    "游乐园": ["乐园", "游乐园"],
    "古镇": ["古镇", "古村", "古城"],
    "寺庙": ["寺", "庙", "祠", "观", "院"],
    "博物馆": ["博物馆", "纪念馆", "遗址"],
    "水上乐园": ["水上乐园", "水世界", "游泳池"],
    "剧场": ["剧场", "演出"],
}


def classify_spot(spot_name: str, notes_raw: str = "") -> dict:
    """Classify a spot into categories.

    Returns {"category": str, "sub_category": str, "tags": list[str]}
    """
    name = spot_name or ""
    notes = notes_raw or ""
    combined = name + " " + notes

    category_scores = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = 0
        for kw in keywords:
            if kw in combined:
                # Multi-char keywords are much more specific
                weight = 3 if len(kw) > 1 else 1
                score += weight
        if score > 0:
            category_scores[cat] = score

    if not category_scores:
        category = "其他"
    else:
        # Sort by score, pick top
        category = max(category_scores, key=category_scores.get)  # type: ignore

    # Sub-category
    sub_category = None
    for sub, keywords in SUB_CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                sub_category = sub
                break
        if sub_category:
            break

    # Tags
    tags = []
    if "夜场" in combined or "夜游" in combined:
        tags.append("夜场")
    if "5A" in name or "AAAAA" in name or "A5" in name:
        tags.append("5A")
    elif "4A" in name or "AAAA" in name or "A4" in name:
        tags.append("4A")
    elif "3A" in name or "AAA" in name or "A3" in name:
        tags.append("3A")
    if "季节性" in notes or "仅夏季" in notes or "仅冬季" in notes:
        tags.append("季节性")
    if "补差" in combined or "补" in combined:
        tags.append("需补差")

    return {
        "category": category,
        "sub_category": sub_category,
        "tags": tags,
    }
