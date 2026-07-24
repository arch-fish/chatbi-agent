"""系统②：带确定性纠错的 workflow（基线的增强，介于单次 NL2SQL 与 agent 之间）。
固定流程：生成 SQL → 执行 → 若报错，把错误喂回重生成一次 → 再执行。
关键：纠错次数由代码写死(MAX_FIX)，不是模型自主决定；无工具选择、无澄清、无统计工具。
用途：评测对照，回答"agent 的收益来自【自主决策】，还是仅仅来自【多试一次纠错】"。"""
from openai import OpenAI
import config
from context import build_context
from db import run_sql
import nl2sql   # 复用 SYSTEM / FEWSHOT / _extract_sql

MAX_FIX = 1     # 确定性纠错次数(固定，非模型决定)

def ask(question, verbose=False):
    ctx = build_context(config.DB_PATH)
    msgs = [{"role": "system", "content": nl2sql.SYSTEM},
            {"role": "user", "content": "数据库说明：\n" + ctx}]
    for q, a in nl2sql.FEWSHOT:
        msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    msgs.append({"role": "user", "content": question})
    client = OpenAI(api_key=config.get_api_key(), base_url=config.BASE_URL)

    sql, err, cols, rows = "", None, None, None
    in_tok=out_tok=calls=0
    for attempt in range(MAX_FIX + 1):          # 首次 + 最多纠错 MAX_FIX 次
        resp = client.chat.completions.create(model=config.MODEL, messages=msgs,
                                              temperature=0, max_tokens=1000)
        _u=getattr(resp,'usage',None); calls+=1
        in_tok+=getattr(_u,'prompt_tokens',0) or 0; out_tok+=getattr(_u,'completion_tokens',0) or 0
        sql = nl2sql._extract_sql(resp.choices[0].message.content)
        if not sql:
            err = "模型未生成有效SQL"; break
        try:
            cols, rows = run_sql(config.DB_PATH, sql)
            err = None; break                    # 成功，退出
        except Exception as e:
            err = str(e)
            if verbose:
                print(f"[第{attempt+1}次报错] {err}")
            if attempt < MAX_FIX:                # 还有纠错机会：喂回错误重生成
                msgs.append({"role": "assistant", "content": f"```sql\n{sql}\n```"})
                msgs.append({"role": "user", "content": f"上面的SQL执行报错：{err}。请修正后只输出新的SQL。"})
    if err:
        return {"question": question, "sql": sql, "error": err, "rows": None, "in_tokens":in_tok,"out_tokens":out_tok,"llm_calls":calls}
    return {"question": question, "sql": sql, "cols": cols, "rows": rows, "in_tokens":in_tok,"out_tokens":out_tok,"llm_calls":calls}
