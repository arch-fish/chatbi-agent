"""Streamlit 演示/内部工具界面：胎儿脑数据 ChatBI。
内部工具级特性：
  - 访问口令：医疗衍生数据，进门要口令(config.get_lab_password)。
  - 持久化记忆：SqliteSaver 把多轮对话记忆落盘，重启不丢、不吃内存。
  - 会话隔离：每个浏览器会话一个 thread_id，多人互不串。
  - 流式：工具轨迹(步骤级) + 最终答案(token级)。
运行(本机)：            streamlit run app.py
运行(内网多人访问)：    streamlit run app.py --server.address 0.0.0.0 --server.port 8501
"""
import uuid
import sqlite3
import streamlit as st
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
import config
import nl2sql
import agent_graph
import tools as raw

st.set_page_config(page_title="胎儿脑数据 ChatBI", page_icon="🧠", layout="centered")

# ---------- 访问口令门(医疗数据必须) ----------
def require_password():
    if st.session_state.get("auth_ok"):
        return
    st.markdown("### 🔒 胎儿脑数据 ChatBI · 请输入访问口令")
    pw = st.text_input("口令", type="password", label_visibility="collapsed")
    if pw:
        if pw == config.get_lab_password():
            st.session_state.auth_ok = True
            st.rerun()
        else:
            st.error("口令错误")
    st.stop()

require_password()

st.title("🧠 胎儿脑数据 ChatBI")
st.caption("用自然语言查询/分析 1761 个胎儿脑、154 个形态学特征。支持多步分析、自我纠错、歧义澄清、多轮追问。")

# Web 端没有命令行 input()，让澄清问题直接作为回复抛给用户
raw.ask_user = lambda question: "（这是需要向用户澄清的问题，请直接把它作为回复呈现给用户）：" + question


# ---------- 全局单例：一个持久化记忆存储 + 一张图，所有会话共享(靠 thread_id 隔离) ----------
@st.cache_resource
def get_graph():
    conn = sqlite3.connect("chat_memory.sqlite", check_same_thread=False)  # 记忆落盘
    return agent_graph.build_graph(checkpointer=SqliteSaver(conn))

def new_conversation():
    """开新对话：只换 thread_id(=新的记忆分区)，不动共享的图/存储。"""
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.seeded = False
    st.session_state.history = []

if "thread_id" not in st.session_state:
    new_conversation()

with st.sidebar:
    st.header("设置")
    mode = st.radio("模式", ["Agent（推荐）", "Baseline（单次NL2SQL）"])
    if st.button("🗑️ 新对话（清空记忆）"):
        new_conversation(); st.rerun()
    st.markdown("**试试这些问题（可连续追问）：**")
    st.markdown("- 华西30周以上个体的左侧皮层平均厚度均值\n"
                "- 那四川呢？　←（追问，靠记忆）\n"
                "- 小脑体积和孕龄有没有相关性\n"
                "- 四川的数据有多少（看它会不会反问）")
    st.caption("工具：query_db · lookup_columns · compute_correlation · ask_user")

for role, content in st.session_state.history:
    st.chat_message(role).markdown(content)


def stream_agent_ui(question):
    graph = get_graph()
    cfg = {"configurable": {"thread_id": st.session_state.thread_id}, "recursion_limit": 12}
    if not st.session_state.seeded:
        payload = {"messages": agent_graph.initial_messages(question)}   # 首轮播种
        st.session_state.seeded = True
    else:
        payload = {"messages": [HumanMessage(question)]}                 # 后续只传新问题
    answer_box = st.empty(); acc = ""
    with st.status("🤔 agent 思考中…", expanded=True) as status:
        for mode_, data in graph.stream(payload, stream_mode=["updates", "messages"], config=cfg):
            if mode_ == "updates":
                for node, pl in data.items():
                    msg = pl["messages"][-1]
                    if getattr(msg, "tool_calls", None):
                        for tc in msg.tool_calls:
                            st.markdown(f"**🤔 调用工具** `{tc['name']}`\n\n参数：`{tc['args']}`")
                    elif node == "tools":
                        st.markdown(f"🔧 **工具返回**：\n```\n{str(msg.content)[:500]}\n```")
            elif mode_ == "messages":
                chunk, meta = data
                txt = getattr(chunk, "content", "") or ""
                if txt and getattr(chunk, "type", "") != "tool":
                    acc += txt; answer_box.markdown(acc)
        status.update(label="✅ 思考完成", state="complete", expanded=False)
    if not acc:
        acc = "(无最终回答)"; answer_box.markdown(acc)
    return acc


q = st.chat_input("问一句，比如：华西30周以上个体的左侧皮层平均厚度均值")
if q:
    st.chat_message("user").markdown(q)
    st.session_state.history.append(("user", q))
    with st.chat_message("assistant"):
        if mode.startswith("Agent"):
            final = stream_agent_ui(q)
            st.session_state.history.append(("assistant", final))
        else:
            with st.spinner("生成 SQL 中…"):
                r = nl2sql.ask(q, verbose=False)
            if r.get("sql"):
                st.markdown("**生成的 SQL：**"); st.code(r["sql"], language="sql")
            if r.get("error"):
                st.error(r["error"]); ans = f"❌ {r['error']}"
            else:
                cols, rows = r.get("cols", []), r.get("rows", [])
                st.markdown("**结果：**"); st.dataframe([dict(zip(cols, row)) for row in rows[:100]])
                ans = f"返回 {len(rows)} 行"
            st.session_state.history.append(("assistant", ans))
