"""agent 能调用的“工具”。每个工具 = 一个普通 Python 函数 + 一份给模型看的说明书(JSON schema)。
模型看说明书决定“调哪个、传什么参数”，我们负责真正执行。"""
import json
import pandas as pd
from db import run_sql, get_conn
import config

# ---------- 工具1：查数据库 ----------
def query_db(sql: str) -> str:
    """执行一条 SELECT，返回结果文本。关键：出错不抛异常，而是把错误信息【返回给模型】，
    让模型看到错误、自己改 SQL 重试——这就是‘自我纠错’的来源。"""
    try:
        cols, rows = run_sql(config.DB_PATH, sql)
    except Exception as e:
        return f"SQL执行出错：{e}。请修正后重试。"
    if not rows:
        return "查询成功，但没有结果行。"
    out = [" | ".join(map(str, cols))]
    for r in rows[:30]:
        out.append(" | ".join(str(x) for x in r))
    if len(rows) > 30:
        out.append(f"...(共 {len(rows)} 行，只显示前30)")
    return "\n".join(out)

# ---------- 工具2：查语义字典(拿准确列名) ----------
def lookup_columns(keyword: str) -> str:
    """按关键词在语义字典里找匹配的字段。用【二元词切分】模糊匹配：关键词切成相邻2字片段
    (皮层厚度->皮层/层厚/厚度)，任一命中即返回，解决“用户词与字段词对不齐”的语义鸿沟。"""
    con = get_conn(config.DB_PATH); cur = con.cursor()
    kw = keyword.strip()
    grams = {kw} | ({kw[i:i+2] for i in range(len(kw)-1)} if len(kw) >= 2 else set())
    conds, params = [], []
    for g in grams:
        conds.append("(chinese_term LIKE ? OR field_name LIKE ?)")
        params += [f"%{g}%", f"%{g}%"]
    rows = cur.execute(
        f"SELECT field_name, chinese_term, unit FROM semantic_dict WHERE {' OR '.join(conds)} LIMIT 25",
        params).fetchall()
    con.close()
    if not rows:
        return f"没找到和“{keyword}”匹配的字段。"
    return "\n".join(f"{f} = {t}{'('+u+')' if u else ''}" for f, t, u in rows)

# ---------- 工具3：相关性统计(SQL 干不了的活，交给 pandas) ----------
def compute_correlation(sql: str, x: str, y: str) -> str:
    """计算两列的皮尔逊相关系数。为什么单独做工具：相关性/趋势这类统计，纯SQL又臭又长还易错，
    pandas 一行 .corr() 就搞定。模型负责给出取数SQL和两列名，我们负责算。"""
    try:
        cols, rows = run_sql(config.DB_PATH, sql)
    except Exception as e:
        return f"SQL执行出错：{e}。请修正后重试。"
    if not rows:
        return "查询没有返回数据，无法计算相关性。"
    df = pd.DataFrame(rows, columns=cols)
    for c in (x, y):
        if c not in df.columns:
            return f"列 {c} 不在查询结果中(结果列有：{list(df.columns)})。请让SQL用别名SELECT出 {x} 和 {y}。"
    a = pd.to_numeric(df[x], errors="coerce")
    b = pd.to_numeric(df[y], errors="coerce")
    d = pd.DataFrame({x: a, y: b}).dropna()
    n = len(d)
    if n < 3:
        return f"有效样本仅 {n} 个，不足以计算相关性。"
    r = float(d[x].corr(d[y]))
    ar = abs(r)
    strength = "几乎无相关" if ar < 0.1 else "弱" if ar < 0.3 else "中等" if ar < 0.5 else "较强" if ar < 0.7 else "强"
    direction = "正" if r >= 0 else "负"
    return f"皮尔逊相关系数 r={round(r,3)}，样本 n={n}；{direction}相关，强度：{strength}。"


# ---------- 工具4：向用户澄清(human-as-tool，人也是一种工具) ----------
def ask_user(question: str) -> str:
    """问题有歧义时，主动向用户提问并等待回答，把回答返回给模型继续。
    为什么做成工具：让‘要不要问、问什么’由模型自己决定，澄清就融进统一的工具循环里。"""
    print(f"\n❓ agent 需要澄清：{question}")
    try:
        ans = input("你的回答> ").strip()
    except (EOFError, KeyboardInterrupt):
        ans = "(用户未回答)"
    return ans or "(用户未回答)"

# ---------- 给模型看的“工具说明书”(JSON schema) ----------
TOOLS_SPEC = [
    {"type": "function", "function": {
        "name": "query_db",
        "description": "执行一条 SQLite SELECT 查询并返回结果。用于最终查数、计数、聚合。",
        "parameters": {"type": "object", "properties": {
            "sql": {"type": "string", "description": "一条完整的 SELECT 语句"}},
            "required": ["sql"]}}},
    {"type": "function", "function": {
        "name": "lookup_columns",
        "description": "按中文关键词查找数据库里的准确字段名。当你不确定某个指标对应哪个列(尤其脑区/FD)时，先用它查清楚再写SQL。",
        "parameters": {"type": "object", "properties": {
            "keyword": {"type": "string", "description": "中文关键词，如 皮层厚度、梭状回、小脑"}},
            "required": ["keyword"]}}},
    {"type": "function", "function": {
        "name": "compute_correlation",
        "description": "计算两个数值列的皮尔逊相关系数。当问题涉及“相关性/关系/是否相关/趋势”时用它，不要在SQL里手算相关系数。你需提供一条SELECT出这两列(含必要过滤，如孕龄要 age_known=1)的SQL，并给两列起好别名后把别名作为 x、y 传入。",
        "parameters": {"type": "object", "properties": {
            "sql": {"type": "string", "description": "SELECT出用于计算的两列的SQL，建议给列起简单别名(如 ga、lv)"},
            "x": {"type": "string", "description": "第一列名(与SQL结果列名/别名一致)"},
            "y": {"type": "string", "description": "第二列名"}},
            "required": ["sql", "x", "y"]}}},
    {"type": "function", "function": {
        "name": "ask_user",
        "description": "当用户的问题有歧义、缺少必要信息时(例如‘四川的数据有多少’没说按个体还是按批次/含不含无孕龄；‘皮层厚度’没说左/右/平均)，先用它向用户提一个澄清问题，拿到答复再继续。不要在信息不明时擅自猜测。",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "要问用户的澄清问题"}},
            "required": ["question"]}}},
]

REGISTRY = {"query_db": query_db, "lookup_columns": lookup_columns,
            "compute_correlation": compute_correlation, "ask_user": ask_user}

def run_tool(name, args_json):
    """根据模型给的工具名和参数(JSON字符串)，执行对应函数。"""
    args = json.loads(args_json) if isinstance(args_json, str) else args_json
    return REGISTRY[name](**args)
