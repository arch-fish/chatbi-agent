"""agent 能调用的“工具”。每个工具 = 一个普通 Python 函数 + 一份给模型看的说明书(JSON schema)。
模型看说明书决定“调哪个、传什么参数”，我们负责真正执行。"""
import json
import pandas as pd
from db import run_sql, get_conn
import config
from glossary import GLOSSARY

# ---------- 工具1：查数据库 ----------
def query_db(sql: str) -> str:
    """执行一条 SELECT，返回结果文本。关键：出错不抛异常，而是把错误信息【返回给模型】，
    让模型看到错误、自己改 SQL 重试——这就是‘自我纠错’的来源。"""
    try:
        cols, rows = run_sql(config.DB_PATH, sql)
    except Exception as e:
        msg = str(e); low = msg.lower()
        if "no such column" in low:
            hint = "字段不存在。请先用 lookup_columns 查到准确字段名，再重写 SQL。"
        elif "no such table" in low:
            hint = "表不存在。可用表：subjects、brain_features、semantic_dict。"
        elif "syntax error" in low or "near " in low:
            hint = "SQL 语法错误，请修正语法后重试。"
        elif "incomplete input" in low:
            hint = "SQL 不完整（可能过长被截断），请精简后重试。"
        elif "readonly" in low or "attempt to write" in low:
            hint = "数据库只读，不能写/改，请改用 SELECT。"
        else:
            hint = "请检查后重试。"
        return f"SQL执行出错：{msg}。{hint}"
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
    """按关键词查找准确字段名。混合检索(向量语义 + 关键词字面，见 retriever.py)：
    向量补'脑积水↔侧脑室'这类跨字面的语义鸿沟，关键词保字面精确；未装向量模型则降级纯关键词。"""
    import retriever
    rows = retriever.hybrid_search(keyword)
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


# ---------- 工具5：口径答疑(查定义，不是查数值) ----------
def explain_metric(term: str) -> str:
    """回答'这个指标怎么算的/什么定义/含不含X/左右哪个'这类查口径的问题。
    在口径词典里按语义(二元词模糊)匹配概念，返回单位、口径说明、相关字段。
    与 query_db 分工：问'是多少'走 query_db；问'怎么定义/怎么算'走这里。"""
    kw=term.strip()
    grams={kw}|({kw[i:i+2] for i in range(len(kw)-1)} if len(kw)>=2 else set())
    hits=[]
    for c in GLOSSARY:
        names=" ".join([c["term"]]+c.get("aliases",[]))
        if any(g in names for g in grams):
            hits.append(c)
    if not hits:
        return f"口径词典暂无'{term}'。可用 lookup_columns 查字段名，或直接查数据。"
    out=[]
    for c in hits[:3]:
        cols="、".join(c["columns"]) if c["columns"] else "-"
        out.append(f"【{c['term']}】单位:{c['unit'] or '-'}\n口径:{c['口径']}\n相关字段:{cols}")
    return "\n\n".join(out)

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
    {"type": "function", "function": {
        "name": "explain_metric",
        "description": "回答'这个指标怎么算的/什么定义/含不含X/左右还是平均/缺失怎么处理'这类查【口径定义】的问题(不是查数值)。例如\"皮层厚度是左右平均还是单侧\"\"侧脑室体积怎么算\"\"孕龄缺失算不算\"。参数为用户问的指标词。",
        "parameters": {"type": "object", "properties": {
            "term": {"type": "string", "description": "要问口径的指标词，如 皮层厚度、侧脑室体积、孕龄"}},
            "required": ["term"]}}},
]

REGISTRY = {"query_db": query_db, "lookup_columns": lookup_columns,
            "compute_correlation": compute_correlation, "ask_user": ask_user,
            "explain_metric": explain_metric}

def run_tool(name, args_json):
    """根据模型给的工具名和参数(JSON字符串)，执行对应函数。"""
    args = json.loads(args_json) if isinstance(args_json, str) else args_json
    return REGISTRY[name](**args)
