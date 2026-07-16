"""LangGraph 版 agent —— 把手写循环重构成显式“状态图”。
行为和 agent.py 完全一样(同样4个工具、同样ReAct循环)，变的只是【组织方式】：
  手写的 for 循环 + if  ->  显式的 节点(Node) + 边(Edge)。
对照表(手写 -> LangGraph)：
  messages 列表         -> State 里的 messages(带 add_messages 自动累加)
  “调模型”那段          -> agent 节点
  “执行工具”那段        -> ToolNode(预置，自动执行 AIMessage 里的 tool_calls)
  if tool_calls: 继续    -> tools_condition 条件边(有工具调用->tools，否则->END)
  for + MAX_STEPS       -> 图自己循环(tools 回到 agent)，上限用 recursion_limit
"""
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
import config
from context import build_context
import tools as raw   # 复用之前写好的工具逻辑

# ---------- 1. 把已有工具逻辑包成 LangChain 工具(加个 @tool 装饰器即可) ----------
@tool
def query_db(sql: str) -> str:
    """执行一条 SQLite SELECT 查询并返回结果。用于查数、计数、聚合。"""
    return raw.query_db(sql)

@tool
def lookup_columns(keyword: str) -> str:
    """按中文关键词查找准确字段名。不确定列名(尤其脑区/FD)时先用它。"""
    return raw.lookup_columns(keyword)

@tool
def compute_correlation(sql: str, x: str, y: str) -> str:
    """计算两个数值列的皮尔逊相关系数。涉及相关性/趋势时用它，不要在SQL里手算。"""
    return raw.compute_correlation(sql, x, y)

@tool
def ask_user(question: str) -> str:
    """当用户问题有歧义或信息不全时，向用户提问澄清，拿到回答再继续。"""
    return raw.ask_user(question)

TOOLKIT = [query_db, lookup_columns, compute_correlation, ask_user]

# ---------- 2. 定义“状态”：图在各节点间传递的数据。这里就是对话消息列表 ----------
class State(TypedDict):
    # Annotated[..., add_messages]：告诉 LangGraph “messages 是要【累加】的”，
    # 每个节点返回的新消息会自动追加进去，不用我们手动 messages.append。
    messages: Annotated[list, add_messages]

SYSTEM = """你是胎儿脑数据分析助手。你不能直接看到数据，只能通过工具查询。
- 需要查数/计数/聚合时，调用 query_db(sql)。
- 不确定某指标对应哪个列(尤其脑区、FD)时，先 lookup_columns(keyword) 查准确列名再写SQL。
- query_db 返回错误信息时，阅读错误、修正 SQL 后重试。
- 涉及“相关性/关系/趋势”，用 compute_correlation(取数SQL+两列别名)，不要在SQL里手算。
- 澄清优先：遇到“口径不明”的问题，必须先调用 ask_user 澄清，不要自行假设。典型口径不明：
    · 计数/范围类里统计单位不明——按个体？按影像文件？按批次？是否只算有孕龄记录的？(例：“四川的数据有多少”“XX有多少”必须先问)
    · 指标未指明左/右/平均(例：“皮层厚度”“小脑体积最大”未说左右时先问)
    · 分组/时间口径不明
  判据：同一问题若存在两种及以上合理口径、会得出不同答案，就先 ask_user；口径已明确时不要多此一举。
- 涉及孕龄的统计要加 age_known=1，并在回答里说明是否排除了无孕龄个体。
- subjects(维度) 与 brain_features(度量) 用 subject_id 关联(JOIN)。含中文列名用双引号。
- 拿到结果后用简洁中文回答，带具体数字。"""

# few-shot 示范：教模型“遇到口径不明的统计问题，先 ask_user 反问”。
# 用“华西有多少数据”这个结构相似但不同的例子，让它学到【模式】而非死记某句。
FEWSHOT = [
    HumanMessage("华西有多少数据"),
    AIMessage(content="", tool_calls=[{"name": "ask_user",
        "args": {"question": "你指按个体数量，还是按影像文件/批次？是否只统计有孕龄记录的个体？"}, "id": "fs1"}]),
    ToolMessage(content="按个体，含全部记录。", tool_call_id="fs1"),
    AIMessage(content="", tool_calls=[{"name": "query_db",
        "args": {"sql": "SELECT COUNT(*) FROM subjects WHERE center='华西'"}, "id": "fs2"}]),
    ToolMessage(content="195", tool_call_id="fs2"),
    AIMessage(content="华西按个体共 195 个（含全部记录）。"),
]

def initial_messages(question):
    """组装初始消息：系统提示(含数据库说明) + few-shot 示范 + 用户真实问题。"""
    msgs = [SystemMessage(SYSTEM + "\n\n数据库说明：\n" + build_context(config.DB_PATH))]
    msgs += FEWSHOT
    msgs.append(HumanMessage(question))
    return msgs

def _make_llm():
    # DeepSeek 兼容 OpenAI 协议，用 LangChain 的 ChatOpenAI 指向它即可。
    # .bind_tools：把工具清单“绑”给模型(相当于手写版里传 tools=TOOLS_SPEC)。
    return ChatOpenAI(model=config.MODEL, base_url=config.BASE_URL,
                      api_key=config.get_api_key(), temperature=0).bind_tools(TOOLKIT)

def agent_node(state: State):
    """‘模型思考’节点：看当前所有消息，产出下一步(要么带tool_calls，要么是最终回答)。"""
    return {"messages": [_make_llm().invoke(state["messages"])]}

def build_graph(checkpointer=None):
    # checkpointer=记忆存储：传了就有多轮记忆(聊天界面用)；不传就无状态(评估用，每题独立)
    g = StateGraph(State)
    g.add_node("agent", agent_node)               # 节点1：模型思考
    g.add_node("tools", ToolNode(TOOLKIT))        # 节点2：执行工具(预置组件，自动跑tool_calls)
    g.add_edge(START, "agent")                    # 入口 -> agent
    g.add_conditional_edges("agent", tools_condition)  # agent后分叉：有tool_calls->tools，否则->END
    g.add_edge("tools", "agent")                  # 工具执行完 -> 回到 agent(这就是“循环”)
    return g.compile(checkpointer=checkpointer)

def run(question, verbose=True):
    graph = build_graph()
    init = {"messages": initial_messages(question)}
    final = None
    # stream：一个节点跑完就吐一次中间状态，正好用来打印“每一步”
    for event in graph.stream(init, {"recursion_limit": 12}):
        for node_name, payload in event.items():
            msg = payload["messages"][-1]
            if verbose:
                if getattr(msg, "tool_calls", None):
                    for tc in msg.tool_calls:
                        print(f"🤔 [{node_name}] 模型决定调用 -> {tc['name']}({tc['args']})")
                elif node_name == "tools":
                    print(f"🔧 [tools] 返回：{msg.content[:200]}")
                elif msg.content:
                    print(f"✅ [{node_name}] 最终回答：{msg.content}")
            final = msg
    return {"question": question, "answer": getattr(final, "content", "")}

if __name__ == "__main__":
    while True:
        try:
            q = input("问> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q in ("quit", "exit", "q", ""):
            break
        run(q); print("=" * 60)
