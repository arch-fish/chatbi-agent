"""评估脚本：对同一套题跑 baseline 和 agent，按题型分类判分，输出对比记分卡。
判分标准随题型不同(见 build_eval.py 注释)。这不是简单'字符串相等'，而是：
  数值题比数字(带容差)、分组题比每组值、相关性题要求用对工具且r接近、歧义题要求会反问、缺失题要求说明排除。"""
import json, re

def extract_numbers(text):
    # 去掉千位逗号(1,181 -> 1181)，避免把一个数拆成两半造成假阴性
    t = str(text).replace(",", "").replace("，", "")
    return [float(x) for x in re.findall(r"-?\d+\.?\d*", t)]

def num_match(text, gold, tol=None):
    if tol is None:
        tol = abs(gold) * 0.01 + 0.02
    return any(abs(n - gold) <= tol for n in extract_numbers(text))

# ---------- 分类判分 ----------
def judge(case, answer, tools_used):
    chk, gold = case["check"], case["gold"]
    if chk == "value":
        return (str(gold) in str(answer)) if isinstance(gold, str) else num_match(answer, gold)
    if chk == "group":
        return all(num_match(answer, v) for v in gold.values())
    if chk == "corr":
        return ("compute_correlation" in tools_used) and num_match(answer, gold, tol=0.05)
    if chk == "clarify":
        return "ask_user" in tools_used
    if chk == "value_list":
        return all(str(x) in str(answer) for x in gold)      # 多个ID都要出现
    if chk == "unanswerable":
        kws = ["没有","无法","不包含","无此","不存在","未收录","查不到","无该","不提供","缺少","未提供","没有该","不涉及","不包括"]
        return any(k in str(answer) for k in kws)             # 识别为答不了(而非瞎编数字)
    if chk == "transparency":
        hit = num_match(answer, gold)
        note = any(k in str(answer) for k in ["排除","未知","缺失","564","无孕龄","孕龄记录"])
        return hit and note
    return False

# ---------- 跑 baseline ----------
def run_baseline(question):
    import nl2sql
    r = nl2sql.ask(question, verbose=False)
    if r.get("error"):
        return f"(错误){r['error']}", []
    text = " ".join(str(x) for row in r.get("rows", []) for x in row)
    return text, []          # baseline 无工具轨迹

# ---------- 跑 agent(带工具轨迹) ----------
def run_agent(question):
    import agent_graph, tools as raw
    from langchain_core.messages import SystemMessage, HumanMessage
    from context import build_context
    import config
    raw.ask_user = lambda question: "（评估模式）请基于最合理的默认假设直接回答。"  # 非阻塞替身
    graph = agent_graph.build_graph()
    init = {"messages": agent_graph.initial_messages(question)}  # 和界面一致：含 few-shot
    state = graph.invoke(init, {"recursion_limit": 12})
    msgs = state["messages"]
    tools_used = [tc["name"] for m in msgs if getattr(m, "tool_calls", None) for tc in m.tool_calls]
    answer = next((m.content for m in reversed(msgs) if getattr(m, "type", None) == "ai" and m.content), "")
    return answer, tools_used

# ---------- 主流程 ----------
def main():
    cases = json.load(open("eval_cases.json", encoding="utf-8"))
    rows = []
    for c in cases:
        b_ans, b_tools = run_baseline(c["question"])
        a_ans, a_tools = run_agent(c["question"])
        b_ok = judge(c, b_ans, b_tools)
        a_ok = judge(c, a_ans, a_tools)
        rows.append((c, b_ok, a_ok))
        print(f"[{c['id']}] {c['category']:14} baseline={'✅' if b_ok else '❌'}  agent={'✅' if a_ok else '❌'}  | {c['question'][:20]}")
    bacc = sum(r[1] for r in rows) / len(rows)
    aacc = sum(r[2] for r in rows) / len(rows)
    print("\n" + "=" * 50)
    print(f"总题数 {len(rows)}   baseline 准确率 {bacc:.0%}   agent 准确率 {aacc:.0%}")
    # 分题型
    from collections import defaultdict
    cat = defaultdict(lambda: [0, 0, 0])
    for c, b, a in rows:
        cat[c["category"]][0] += 1; cat[c["category"]][1] += b; cat[c["category"]][2] += a
    print("\n分题型(题数 / baseline对 / agent对):")
    for k, (n, b, a) in cat.items():
        print(f"  {k:16} {n} / {b} / {a}")

if __name__ == "__main__":
    main()
