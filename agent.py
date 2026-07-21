"""首个工具调用 agent —— 手写循环版(先不用 LangGraph，为了讲清机制)。
与基线的根本区别：不再是‘一次生成SQL就结束’，而是一个循环：
  模型看情况 -> 决定调哪个工具 -> 我们执行 -> 结果回喂给模型 -> 模型再决定 ...
  直到模型认为够了，给出最终自然语言回答。
控制权在【模型】手里，这就是 agent。"""
from openai import OpenAI
import config
from context import build_context
from tools import TOOLS_SPEC, run_tool

SYSTEM = """你是胎儿脑数据分析助手。你不能直接看到数据，只能通过工具查询。
工作方式：
- 需要查数/计数/聚合时，调用 query_db(sql) 执行 SELECT。
- 不确定某指标对应哪个列时(尤其具体脑区、FD)，先调用 lookup_columns(keyword) 查准确列名，再写 SQL。
- query_db 若返回错误信息，请阅读错误、修正 SQL 后重试。
- 涉及“相关性/关系/趋势”的问题，用 compute_correlation 工具(给取数SQL和两列别名)，不要在SQL里手算相关系数。
- 澄清优先：遇到“口径不明”的问题，必须先调用 ask_user 澄清，不要自行假设。典型口径不明：
    · 计数/范围类里统计单位不明——按个体？按影像文件？按批次？是否只算有孕龄记录的？(例：“四川的数据有多少”“XX有多少”必须先问)
    · 指标未指明左/右/平均(例：“皮层厚度”“小脑体积最大”未说左右时先问)
    · 分组/时间口径不明
  判据：同一问题若存在两种及以上合理口径、会得出不同答案，就先 ask_user；口径已明确时不要多此一举。
- 用户问'指标怎么算的/什么定义/含不含X/左右还是平均/缺失怎么处理'这类【查口径】问题，用 explain_metric(不要去查数值)；问'是多少'才用 query_db。
- 涉及孕龄的统计要加 age_known=1，并在最终回答里说明是否排除了无孕龄个体。
- subjects(维度) 与 brain_features(度量) 用 subject_id 关联(JOIN)。含中文列名用双引号。
- 拿到结果后，用简洁中文回答用户，带上具体数字。"""

MAX_STEPS = 6   # 循环上限：防止模型无限调用工具(必须有的安全阀)

def run(question, verbose=True):
    client = OpenAI(api_key=config.get_api_key(), base_url=config.BASE_URL)
    ctx = build_context(config.DB_PATH)
    messages = [
        {"role": "system", "content": SYSTEM + "\n\n数据库说明：\n" + ctx},
        {"role": "user", "content": question},
    ]

    for step in range(1, MAX_STEPS + 1):
        resp = client.chat.completions.create(
            model=config.MODEL, messages=messages,
            tools=TOOLS_SPEC, temperature=0)      # 关键：把工具清单交给模型
        msg = resp.choices[0].message

        # 情况A：模型决定“调用工具”
        if msg.tool_calls:
            # 把模型这轮的决定原样记进对话历史(必须，否则下一轮模型不知道自己刚说了啥)
            messages.append(msg)
            for tc in msg.tool_calls:
                name = tc.function.name
                args = tc.function.arguments
                if verbose:
                    print(f"🤔 第{step}步：模型决定调用工具 -> {name}({args})")
                result = run_tool(name, args)
                if verbose:
                    print(f"🔧 工具返回：\n{result}\n")
                # 把工具结果回喂给模型(role=tool)，模型下一轮就能看到
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            continue   # 回到循环顶部，让模型看着结果再决定下一步

        # 情况B：模型不调工具了，说明它认为可以给最终答案
        if verbose:
            print(f"✅ 第{step}步：模型给出最终回答：\n{msg.content}")
        return {"question": question, "answer": msg.content, "steps": step}

    return {"question": question, "answer": "(达到步数上限)", "steps": MAX_STEPS}

if __name__ == "__main__":
    while True:
        try:
            q = input("问> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q in ("quit", "exit", "q", ""):
            break
        run(q); print("=" * 60)
