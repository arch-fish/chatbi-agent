# ChatBI · 面向科研数据的分析型问数 Agent

> 用自然语言查询与分析结构化科研数据 —— 一句话完成筛选、聚合、跨中心对比与相关性分析。

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-ReAct%20Agent-1C3C3C)
![LLM](https://img.shields.io/badge/LLM-DeepSeek-4D6BFE)
![UI](https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit&logoColor=white)

基于 LangGraph 的 ReAct Agent，面向多中心胎儿脑 MRI 的形态学指标（1761 例 × 154 指标）。相比单次 NL2SQL，在自建 36 题离线评测上任务通过率 **67% → 89%**——增量优势集中在基线做不到的能力（自我纠错、歧义澄清、统计、防幻觉）。

> 数据含隐私（`subject_id` 嵌姓名拼音），不随仓库发布。仓库提供 `make_synthetic_data.py` 生成同结构的合成数据供运行；README 中的评测数字为真实数据上的结果。

## 特性

- **ReAct Agent（LangGraph）**：模型自主编排工具、SQL 出错自我纠正、歧义主动澄清、多轮记忆
- **5 个工具**：库查询、字段语义检索（schema-linking）、pandas 统计、向用户澄清（human-in-the-loop）、**指标口径答疑**（区分“查数值”与“查定义”，如“皮层厚度是左右平均还是单侧”）
- **口径答疑 / 防幻觉**：概念级口径词典，回答指标怎么算、缺失如何处理，先对齐口径再取数，降低选错列
- **混合检索（schema-linking）**：154 列宽表按需检索字段，**向量语义 + 关键词字面**合并（`retriever.py`），补“脑积水↔侧脑室”这类跨字面的语义鸿沟；离线实验（12 题语义查询）：关键词 58% → 向量 83% → **混合 92%**（向量为可选依赖，未装则降级纯关键词）
- **安全**：只读连接 + 语句白名单双层防护，拦截破坏性 SQL
- **可观测**：每次运行记录延迟 / token / 成本 / 工具轨迹（`trace.py`，落盘 JSONL + 聚合汇总），生产可换 LangSmith
- **评测**：参考 Spider / BIRD 维度的 36 题分类型评测，baseline vs agent 对比 + 失败归因
- **界面**：Streamlit，流式展示工具调用过程 + 多轮对话

## 架构

```mermaid
flowchart LR
    U[用户问题] --> A["agent 节点<br/>调模型 · 决策下一步"]
    A -->|有 tool_calls| T["tools 节点<br/>执行工具"]
    A -->|无 tool_calls| E[最终回答]
    T -->|结果累加进 State| A
    T -.-> Q1[query_db]
    T -.-> Q2[lookup_columns]
    T -.-> Q3[compute_correlation]
    T -.-> Q4[ask_user]
    T -.-> Q5[explain_metric]
```

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env            # 填入 DEEPSEEK_API_KEY
python make_synthetic_data.py   # 生成合成数据 data.db（脱敏，可公开运行）
python build_eval.py            # 生成评测集

streamlit run app.py            # Web 界面（推荐）
python agent_graph.py           # 命令行 agent
python eval.py                  # baseline vs agent 评测
```

## 评测结果

36 题离线评测（DeepSeek-V4-Flash，固定配置单次实验）：

| 类别 | 题数 | Baseline | Agent |
|---|---:|---:|---:|
| 纯查询 / SQL | 23 | 23 | 19 |
| 相关性统计 | 4 | 0 | **4** |
| 歧义澄清 | 3 | 0 | **3** |
| 不可答 / 防幻觉 | 3 | 0 | **3** |
| 缺失 / 脏数据 | 3 | 1 | **3** |
| **合计** | 36 | **67%** | **89%** |

Agent 并非处处更优——纯 SQL 上 baseline 反而更稳；优势全部来自 baseline 结构上无法完成的四类能力。判分为启发式（数值容差 + 关键词 + 行为判据），更严谨可加 LLM-as-judge。

## 目录结构

```
chatbi/
├── 核心         config.py  db.py  context.py  tools.py  retriever.py  glossary.py
├── 基线/Agent   nl2sql.py  agent.py  agent_graph.py
├── 数据/评测    build_db.py  make_synthetic_data.py  build_eval.py  eval.py  exp_retrieval.py  questions.txt
├── 可观测       trace.py
├── 入口         app.py  cli.py  run_batch.py  check_deepseek.py
└── README.md  LICENSE  requirements.txt  .env.example
```

## 设计要点

- **为什么用 Agent 而非纯 workflow**：查询/过滤这类可控路径 workflow 即可；但开放式分析（步数与路径依赖中间结果）无法预先画出流程图，需模型运行时自主决策。项目保留单次 NL2SQL 作对照，用评测量化收益。
- **能力靠加工具扩展，不改控制流**：新增能力＝加一个工具，Agent 循环不变。
- **易错、要精确的操作卸载给确定性工具**：如相关性交给 pandas，而非让模型手写复杂 SQL。

## 受约束的分析，而不是自由生成 SQL

一开始我以为问数就是“把问题丢给大模型生成 SQL”，做完基线才发现不行——它会选错列、会瞎猜口径、遇到歧义直接编一个。所以我把它往“受约束的分析”方向做，主要加了四类约束：

- **口径约束**：查数前先对齐指标定义（`explain_metric` + 口径词典），比如“皮层厚度”到底指左/右/平均，先说清再取数。
- **权限约束**：数据库只读打开 + 语句白名单，模型再怎么出错也删不了、改不了数据。
- **停止约束**：循环设了最大步数，防止无限调用工具停不下来。
- **人工介入**：问题歧义时用 `ask_user` 把口径交回给用户确认，而不是替用户猜。

这几条不是一开始就想好的，是做基线踩坑之后一条条补的。合起来的意思是：agent 有自由（自己决定调哪个工具、要不要重试），但这个自由是被框住的。

## 局限

- 评测为 36 题、单次运行、题目自出，存在过拟合风险；后续拟纳入真实用户提问、扩题量、多次运行报方差。
- 向量检索对英文缩写（GA→孕龄）、冷僻表述仍会漏，非银弹；且需加载 embedding 模型，未装则降级纯关键词。
- 课题组内部工具规模（SQLite / 单机），非生产级高并发；无 FastAPI / 容器化（面向内部工具刻意从简）。

## 技术栈

Python · LangGraph · LangChain · DeepSeek (Function Calling) · SQLite · pandas · Streamlit
