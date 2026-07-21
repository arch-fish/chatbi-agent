"""可观测：每次 agent 运行记录轨迹 + 指标(延迟/token/成本)，落盘 JSONL 便于事后分析。
指标：latency(秒)、步数、工具调用序列、输入/输出 token(取自模型返回的 usage_metadata)、估算成本。
生产可无缝换 LangSmith：设 LANGCHAIN_TRACING_V2=true + LANGSMITH_API_KEY 即接入云端追踪。
用法：python trace.py "华西30周以上皮层厚度均值"
      python trace.py --summary          # 聚合已有 traces.jsonl
"""
import time, json, sys, os
import config

# DeepSeek-v4-flash 估算价(元/百万 token)，仅供成本估算
PRICE_IN, PRICE_OUT = 1.0, 2.0
TRACE_FILE = os.path.join(os.path.dirname(__file__), "traces.jsonl")

def traced_run(question):
    import agent_graph
    graph = agent_graph.build_graph()
    init = {"messages": agent_graph.initial_messages(question)}
    t0 = time.time()
    state = graph.invoke(init, {"recursion_limit": 12})
    latency = round(time.time() - t0, 2)

    msgs = state["messages"]
    tools_used, in_tok, out_tok, llm_calls = [], 0, 0, 0
    for m in msgs:
        um = getattr(m, "usage_metadata", None)
        if not um:
            continue                       # 只统计真实 LLM 输出(few-shot 伪造消息无 usage，跳过)
        llm_calls += 1
        in_tok += um.get("input_tokens", 0)
        out_tok += um.get("output_tokens", 0)
        if getattr(m, "tool_calls", None):
            tools_used += [tc["name"] for tc in m.tool_calls]
    answer = next((m.content for m in reversed(msgs)
                   if getattr(m, "type", None) == "ai" and m.content), "")
    cost = round(in_tok / 1e6 * PRICE_IN + out_tok / 1e6 * PRICE_OUT, 5)

    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "question": question,
           "latency_s": latency, "llm_calls": llm_calls,
           "tool_steps": len(tools_used), "tools_used": tools_used,
           "input_tokens": in_tok, "output_tokens": out_tok,
           "cost_rmb_est": cost, "answer": answer[:120]}
    with open(TRACE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec

def summary():
    if not os.path.exists(TRACE_FILE):
        print("暂无 traces.jsonl"); return
    recs = [json.loads(l) for l in open(TRACE_FILE, encoding="utf-8") if l.strip()]
    n = len(recs)
    avg = lambda k: round(sum(r.get(k, 0) for r in recs) / n, 3)
    print(f"共 {n} 次运行")
    print(f"  平均延迟: {avg('latency_s')} s")
    print(f"  平均工具步数: {avg('tool_steps')}")
    print(f"  平均 token: 入 {avg('input_tokens'):.0f} / 出 {avg('output_tokens'):.0f}")
    print(f"  平均估算成本: ¥{avg('cost_rmb_est')}")
    from collections import Counter
    tc = Counter(t for r in recs for t in r.get("tools_used", []))
    print(f"  工具使用分布: {dict(tc)}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--summary":
        summary()
    elif len(sys.argv) > 1:
        r = traced_run(" ".join(sys.argv[1:]))
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print('用法: python trace.py "你的问题"   或   python trace.py --summary')
