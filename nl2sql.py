"""最简 NL2SQL：中文问题 -> LLM 生成 SQL -> 执行 -> 结果。
这是【单次调用基线版】：没有重试、没有澄清、没有多步。
故意如此——它是后面 LangGraph agent 版的对照组，评估时用来量化“agent化带来多少提升”。"""
import re
from openai import OpenAI
import config
from context import build_context
from db import run_sql

SYSTEM = """你是把中文问题转成 SQLite SQL 的助手。严格遵守：
1. 只输出一条 SELECT 语句，不要输出解释文字。
2. subjects(过滤维度) 与 brain_features(度量) 通过 subject_id 关联(JOIN)。
3. 孕龄 gestational_age 有缺失。凡涉及孕龄的查询，必须加 age_known=1(或 gestational_age IS NOT NULL)，避免把缺失当成有效值。
4. 含中文的列名必须用双引号包裹，例如 "FD_roi_055_左梭状回"。
5. 聚合的数值结果用 ROUND(值, 2)。
输出用 ```sql ``` 代码块包裹。"""

FEWSHOT = [
    ("广州一共有多少个体",
     '```sql\nSELECT COUNT(*) FROM subjects WHERE center=\'广州\';\n```'),
    ("四川 30 周以上个体的左小脑体积平均值",
     '```sql\nSELECT ROUND(AVG(b.cerebellum_left_volume_ml),2)\nFROM subjects s JOIN brain_features b ON s.subject_id=b.subject_id\nWHERE s.center=\'四川\' AND s.age_known=1 AND s.gestational_age>30;\n```'),
]

def _extract_sql(text):
    """稳健提取 SQL：兼容 闭合代码块 / 未闭合代码块(截断) / 裸SELECT。"""
    text = (text or "").strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)   # 正常闭合
    if m:
        sql = m.group(1)
    else:                                                          # 未闭合(如被max_tokens截断)
        sql = re.sub(r"^```sql\s*", "", text, flags=re.I)          # 去掉起始围栏
        sql = re.sub(r"```\s*$", "", sql)                          # 去掉可能的结尾围栏
    return sql.strip().rstrip(";").strip()

def ask(question, verbose=True):
    ctx = build_context(config.DB_PATH)
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": "数据库说明：\n" + ctx}]
    for q, a in FEWSHOT:
        msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    msgs.append({"role": "user", "content": question})

    client = OpenAI(api_key=config.get_api_key(), base_url=config.BASE_URL)
    resp = client.chat.completions.create(model=config.MODEL, messages=msgs,
                                          temperature=0, max_tokens=1000)  # 400->1000，避免复杂SQL被截断
    raw = resp.choices[0].message.content
    sql = _extract_sql(raw)
    _u = getattr(resp, 'usage', None)
    _tok = {'in_tokens': getattr(_u,'prompt_tokens',0) or 0, 'out_tokens': getattr(_u,'completion_tokens',0) or 0, 'llm_calls': 1}

    # SQL 为空 = 模型没给有效SQL(如遇歧义摆烂)。显式报出，并附原始回复便于诊断
    if not sql:
        if verbose:
            print("── 模型未生成有效SQL，原始回复 ──\n" + (raw or "(空)"))
        return {"question": question, "sql": "", "error": "模型未生成有效SQL", "raw": raw, "rows": None, **_tok}

    if verbose:
        print("── LLM 生成的 SQL ──\n" + sql)
    try:
        cols, rows = run_sql(config.DB_PATH, sql)
    except Exception as e:
        if verbose:
            print("── 执行出错 ──\n" + str(e))
        return {"question": question, "sql": sql, "error": str(e), "rows": None, **_tok}
    if verbose:
        print("── 结果 ──"); print(cols)
        for r in rows[:20]:
            print(r)
        if len(rows) > 20:
            print(f"...(共 {len(rows)} 行)")
    return {"question": question, "sql": sql, "cols": cols, "rows": rows, **_tok}
