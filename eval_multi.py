"""三系统多指标评测：单次NL2SQL / 带纠错workflow / Agent。
回答关键问题：agent 的收益来自【自主决策】，还是仅仅来自【多试一次纠错】？
指标：分题型准确率(均值±方差)、平均LLM调用数、平均token、P50/P95延迟、平均成本。
本机运行(约 3系统×36题×3次 ≈ 300+ 次真实调用，几分钟)：python eval_multi.py
"""
import json, time, statistics
from collections import defaultdict
import config
import nl2sql, workflow_fix, trace
from eval import judge

N_RUNS = 3
PRICE_IN, PRICE_OUT = 1.0, 2.0     # 元/百万token
SYSTEMS = ["①单次NL2SQL", "②纠错workflow", "③Agent"]

def rows_to_text(r):
    if r.get("error"): return f"(错误){r['error']}"
    return " ".join(str(x) for row in r.get("rows", []) for x in row)

import time as _t
def _with_retry(fn, tries=3):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                raise
            _t.sleep(2 * (i + 1))   # 退避重试：2s,4s

def run_one(system, q):
    t0 = time.time()
    if system == "③Agent":
        r = trace.traced_run(q)
        d = {"answer": r["answer"], "tools": r["tools_used"], "calls": r["llm_calls"],
             "tin": r["input_tokens"], "tout": r["output_tokens"]}
    else:
        r = (nl2sql if system == "①单次NL2SQL" else workflow_fix).ask(q)
        d = {"answer": rows_to_text(r), "tools": [], "calls": r.get("llm_calls", 1),
             "tin": r.get("in_tokens", 0), "tout": r.get("out_tokens", 0)}
    d["lat"] = time.time() - t0
    return d

def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs)-1, int(round(p/100*(len(xs)-1))))], 2) if xs else 0

def main():
    cases = json.load(open("eval_cases.json", encoding="utf-8"))
    import tools as raw
    raw.ask_user = lambda q: "（评估模式）请基于最合理默认假设直接回答。"   # 非阻塞
    n = len(cases)
    per_run_acc = {s: [] for s in SYSTEMS}
    lat = {s: [] for s in SYSTEMS}; calls = {s: [] for s in SYSTEMS}
    tin = {s: [] for s in SYSTEMS}; tout = {s: [] for s in SYSTEMS}
    cat_ok = {s: defaultdict(int) for s in SYSTEMS}
    cat_n = defaultdict(int)

    for run in range(N_RUNS):
        acc = {s: 0 for s in SYSTEMS}
        for c in cases:
            if run == 0: cat_n[c["category"]] += 1
            for s in SYSTEMS:
                try:
                    d = _with_retry(lambda: run_one(s, c["question"]))
                except Exception as e:
                    print(f"  [跳过] {s} / {c['id']}: {str(e)[:60]}")
                    d = {"answer": f"(调用失败){e}", "tools": [], "calls": 0, "tin": 0, "tout": 0, "lat": 0}
                ok = judge(c, d["answer"], d["tools"])
                acc[s] += ok; cat_ok[s][c["category"]] += ok
                lat[s].append(d["lat"]); calls[s].append(d["calls"])
                tin[s].append(d["tin"]); tout[s].append(d["tout"])
        for s in SYSTEMS:
            per_run_acc[s].append(acc[s] / n)
        print(f"  第{run+1}次完成")

    print(f"\n=== 三系统 × {n} 题 × {N_RUNS} 次 ===")
    print(f"{'系统':14}{'准确率(均值±std)':18}{'平均调用':8}{'平均token':10}{'P50延迟':8}{'P95延迟':8}{'平均成本¥'}")
    for s in SYSTEMS:
        m = statistics.mean(per_run_acc[s]); sd = statistics.pstdev(per_run_acc[s])
        ac = statistics.mean(calls[s]); ai = statistics.mean(tin[s]); ao = statistics.mean(tout[s])
        cost = ai/1e6*PRICE_IN + ao/1e6*PRICE_OUT
        print(f"{s:14}{m:.0%} ± {sd:.0%}      {ac:>5.1f}   {ai+ao:>7.0f}   {pct(lat[s],50):>5.1f}s  {pct(lat[s],95):>5.1f}s  {cost:.4f}")

    print("\n分题型准确率(占比，3次累计):")
    print(f"{'题型':16}" + "".join(f"{s:14}" for s in SYSTEMS))
    for cat in sorted(cat_n):
        tot = cat_n[cat] * N_RUNS
        print(f"{cat:16}" + "".join(f"{cat_ok[s][cat]/tot:>10.0%}    " for s in SYSTEMS))

if __name__ == "__main__":
    main()
