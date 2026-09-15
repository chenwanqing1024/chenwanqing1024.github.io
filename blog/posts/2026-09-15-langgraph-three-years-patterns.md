---
title: LangGraph 3 年：什么时候用 graph / 什么时候用 harness / 什么时候用 loop——决策框架
date: 2026-09-15
tags: [Agent, LangGraph, 工程哲学, 决策框架, 工程实践]
summary: LangGraph 3 年的核心经验：什么时候把 Agent 表达为 graph（结构已知、路径确定）、什么时候用 agent harness（结构未知、靠模型推理）、什么时候用 loop（最简版本）。3 个关键 lesson：agent graph 通常不是 DAG、loop 就是简单 graph、动态 transition 重要。附决策框架 + 简历项目骨架。
source-url: https://www.langchain.com/blog/3-years-of-graph-engineering-with-langgraph
source-title: 3 Years of Graph Engineering with LangGraph
source-author: Sydney Runkle / Harrison Chase (LangChain)
---

## 引子

LangGraph 现在每月 **65M+ 下载**。LangChain 团队 3 年 build 出的核心 wisdom：**什么时候用 graph / 什么时候用 harness / 什么时候用 loop**——三者不是替代关系，是**同一个思想在不同抽象层级的表达**。

这篇文章不是讲 LangGraph 怎么用，是讲**"图作为 Agent 抽象"的工程判断标准**。面试讲 Agent 架构选型，这 3 个 lesson + 决策框架直接搬。

---

## 核心思想：把"你对系统的先验"编码进图

> "**Representing agentic systems as graphs lets you impose your preconceptions of how the system should work into more constrained paths, not relying solely on the judgement of the LLM.**"

**Graph 的本质**：**把你对"系统应该怎么工作"的领域知识**编码进**节点（做什么）+ 边（什么时候走）+ state（流动什么）**。

**3 种 primitive 的本质**：

| Primitive | 本质 | 你对系统的先验 |
|---|---|---|
| **Loop** | Agent 跑一个循环调 LLM → tool → ... | 不知道具体路径，靠模型推理 |
| **Graph** | 你知道大致路径，让模型在某几步选择 | **部分先验**：固定框架 + 局部决策 |
| **Harness** | 提供 plan / delegate / context management 等基础设施 | **少量先验**：模型自己决定大部分 |

**3 个抽象不是替代，是同一思想的层级**：

> "Graph engineering isn't a new idea. It's the latest name for a well established approach to building reliable agents. **It's the same idea behind loop engineering and harness engineering: building putting model reasoning in the right places, with the right context, at each step.**"

**面试可讲角度**：这是 *abstraction levels for agent control* 的工程化。**Loop / Graph / Harness 是同一个思想在不同抽象层级的实现**——**你的先验越多用 graph，你的先验越少用 harness**。**没有"哪个最好"，只有"哪个对你这个任务最合适"**。

---

## Lesson 1：Agent graph 通常不是 DAG

> "Production agents need cycles: **retrying failed tool calls, asking users for missing information, revising answers after validation, calling tools repeatedly until they have enough context, and pausing for human input before resuming.** Looping is a core part of agentic systems, so they are likely not DAGs."

**5 个生产 Agent 必须能 cycle 的场景**：

1. **重试失败 tool call**（timeout / 5xx / rate limit）
2. **问用户补缺失信息**（"你的订单号？"）
3. **验证后修正答案**（retrieval 后 self-check 不一致就重做）
4. **重复调 tool 直到 context 够**（deep research 跑到满足为止）
5. **暂停等人工输入再恢复**（human-in-the-loop checkpoint）

**工程含义**：用 LangGraph 时**不要害怕 cycle**——cycle 是 Agent 的基本能力。

**面试可讲角度**：**传统 workflow / ETL 工具假设 DAG**（Airflow / Prefect / Temporal DAG 模式）——Agent 不是 DAG。**Agent 框架必须原生支持 cycle + checkpoint + resume**。**这是 LangGraph vs 传统 workflow 的根本区别**。

---

## Lesson 2：Loop 就是简单 graph

> "**Loop engineering isn't an alternative to graphs, so much as a simple version of them.** A loop is just a directed, cyclic graph."

**关键含义**：

- LangChain framework 本身就是 LangGraph 之上的一层——`AgentExecutor` 就是循环
- Loop 适用于"你对系统先验很少"的场景
- Loop 比 graph 简单，但灵活度低（容易"乱跑"）

**面试可讲角度**：这是 *abstraction levels* 的工程化体现。**Loop 是 graph 的特例（"只有一个节点 + 跳回自己的边"）**。**不要把"用 loop 还是用 graph"当成对立选择——它们是同一抽象的不同参数化**。

---

## Lesson 3：动态 transition（Send API）很重要

> "You do not always want to define every edge up front. Sometimes a node decides at runtime how much work to create. **Map-reduce is the classic case**: split an input into pieces, send each to a worker, then combine the results. The number of workers depends on the input, and you do not know that number in advance."

**LangGraph 的 Send API**：

```python
# 静态边：明确定义 N 个 worker
graph.add_edge("split", "worker_1")
graph.add_edge("split", "worker_2")

# 动态边：runtime 决定 N 个 worker（map-reduce）
graph.add_conditional_edges(
    "split",
    lambda state: [Send("worker", item) for item in state["items"]]
)
```

**关键工程含义**：

> "Useful agent systems mix known structure with runtime variability. **You might know research should fan out and then synthesize, but not how many sources there will be.** You might know a supervisor should delegate to workers, but not know which specific workers to use until the task starts."

**关键判断**：**Graph 不是"完全静态"——它是"框架静态 + 局部动态"**。**Send API 让你定义结构 + 留出运行时灵活性**。

**面试可讲角度**：这是 *static structure + dynamic routing* 的工程取舍。**Airflow / Prefect 这类纯静态 workflow 做不到——Agent 图必须支持 runtime-decided fan-out**。

---

## 决策框架：什么时候用哪个

```
                 你对系统结构的先验有多少？
                          │
       ┌──────────────────┼──────────────────┐
       │                  │                  │
    几乎为零            部分已知            完全已知
       │                  │                  │
       ↓                  ↓                  ↓
   [Agent Loop]      [LangGraph]         [Static Workflow]
   (ReAct / DeepAgents) (graph + LLM 节点)  (Airflow / DAG)
```

**3 个具体例子**：

| 任务 | 先验 | 选哪个 | 为什么 |
|---|---|---|---|
| **Deep research** | 很少——查询路径不可预测 | **Deep Agents / Loop** | 需要 plan / delegate / context management，路径动态 |
| **Support Agent** | 部分——分类 → 搜索 → 答复 | **LangGraph** | 3 个固定阶段，每阶段内模型决定 |
| **ETL pipeline** | 全部——步骤固定 | **Airflow / Prefect** | 不需要 LLM 决策，纯确定性 workflow |

**LangChain 自家演进**：早期 deep research 用 LangGraph 写死 workflow → 后来改用 Deep Agents harness，因为**结构动态性太大，graph 写不出来**。GPT Researcher 走过同样的路——从 graph-shaped multi-agent 改成 Deep Agents。

**关键判断**：

> "**Graphs let you encode that structure directly: the valid paths, where the model gets to choose, and where the system should enforce deterministic behavior instead of hoping the model makes the right call every time.**"

**不要试图让模型推理决定"路径"——把路径画出来**。**让模型推理决定"在某一步做什么"**。**这是 graph vs loop 的核心分界**。

---

## What's actually new：节点可以是"完整 Agent"

**3 年前 LangGraph 节点**：deterministic code 或 single LLM call。

**现在的节点**：**可以是完整 Agent run**——你在 orchestrating agents，不只是 LLM calls。

**例子：Docs Agent**

```
[Slack request] → [Slack API node: 固定代码]
                       ↓
              [Classifier node: LLM 单次调用，无 tools]
                       ↓
            ┌──────────┴──────────┐
            ↓                     ↓
[Reference Docs Agent]    [Conceptual Docs Agent]
(完整 agent run + tools)   (完整 agent run + tools)
            ↓                     ↓
            └──────────┬──────────┘
                       ↓
            [Synthesize node: LLM 单次调用]
                       ↓
            [Linear API node: 固定代码]
                       ↓
            [PR ready for review]
```

**3 个类型的节点**：

1. **Fixed steps**（Slack / Linear API）—— 纯代码，无 LLM
2. **Model steps**（Classifier / Synthesize）—— 单次 LLM 调用，无 tools
3. **Agent steps**（Reference Docs / Conceptual Docs）—— 完整 agent run

**确定性 vs agentic 的混合**就是这种架构能"可预测 + 强大 + 高效"的原因。

**面试可讲角度**：这是 *nested agent composition* 的工程化。**Agent 可以嵌套在 Agent 里——外层 graph 管"结构"，内层 agent 管"复杂任务"**。**这是 single-agent loop 做不到的扩展性**。

---

## 简历可直接借用的项目骨架（Agent 架构选型 / 框架设计类）

```
项目名：[业务名] 多 Agent 平台 / Agent 编排框架

角色：核心工程师 / Agent 架构师

核心架构决策：
1. 何时用 Loop / Graph / Harness：
   - Loop = 几乎无先验
   - Graph = 部分先验 + 局部模型决策
   - Harness = 大量先验 + 复杂任务
2. 节点可以是 LLM call / 工具调用 / 完整 Agent run
3. 支持动态 transition（map-reduce / supervisor-worker）

3 个关键 engineering lesson：
1. Agent graph 不是 DAG——必须支持 cycle + checkpoint + resume
2. Loop 就是简单 graph——同一思想的不同参数化
3. 动态 transition 重要——Send API 让 graph 既结构化又灵活

工具栈：[LangGraph / Deep Agents / Claude Agent SDK]

成果（量化）：
- Agent graph 节点数：[N] 个
- Sub-agent 嵌套深度：[M] 层
- Cycle 支持：[X] 类（retry / ask-user / self-validate / human-in-the-loop）
- 动态 fan-out：[Y] 类场景（map-reduce / supervisor dispatch）
- 决策框架覆盖率：[Z]% 任务用合适抽象
```

**面试常被问到的延伸问题**：
- "为什么用 graph 而不是 loop？" → **我的任务有可编码的结构**——分类 → 搜索 → 答复这种框架可以画出来
- "Graph 和 DAG 有什么区别？" → **Agent graph 必须支持 cycle**——retry / ask-user / self-validate 都是 cycle，传统 DAG workflow 框架做不到
- "节点可以是 Agent 吗？" → **可以**——外层 graph 管结构，内层 agent 管复杂任务
- "什么时候用静态图什么时候用动态图？" → **静态图 = 路径固定**，**动态图 = 节点 runtime 决定派多少 worker**（map-reduce / supervisor-worker）
- "Loop / Graph / Harness 怎么选？" → **你对系统结构的先验有多少**——几乎为零用 loop，部分已知用 graph，几乎完全已知用静态 workflow

---

## 配套阅读

- **同框架多业务**：[Paid Media Agent](blog/posts/2026-09-15-agent-paid-media-workspace-five-lessons.md) — Deep Agents 用法案例
- **架构演进**：[Sidekick](blog/posts/2026-09-15-agent-sidekick-bounded-responsibilities.md) — 单 Agent → 多层架构
- **底层 SDK**：[Claude Agent SDK](blog/posts/2026-09-15-claude-agent-sdk-engineering.md) — SDK 层的实现细节

参考资料：

- [3 Years of Graph Engineering with LangGraph](https://www.langchain.com/blog/3-years-of-graph-engineering-with-langgraph) — Sydney Runkle, Harrison Chase
- [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview)
- [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview)
- [Cognitive Architectures](https://www.langchain.com/blog/what-is-a-cognitive-architecture)
