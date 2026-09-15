---
title: monday.com Sidekick：为什么"加更多 tool"反而让 Agent 更差——5 层架构 + Tool/Subagent/Sandbox 决策树
date: 2026-09-15
tags: [Agent, Sidekick, 多 Agent, 工程教训, 工程实践]
summary: monday.com Sidekick 从单 Agent + N tools 起步，在生产里发现"加 tool 反而让 Agent 更差"——5 个具体失败模式。重构成 5 层架构（context/permission → orchestrator → subagents → tools → sandbox），并给出 tool vs subagent vs sandbox 的决策树。附完整简历项目骨架。
source-url: https://www.langchain.com/blog/building-monday-com-sidekick-why-capable-agents-need-more-than-just-tools
source-title: Building monday.com Sidekick: why capable agents need more than just tools
source-author: Omri Bruchim (monday.com)
---

## 引子

monday.com Sidekick V1：**1 个 general-purpose Agent + 1 个 growing list of tools**。V1 看起来"能力越来越强"，生产里发现"能力越来越弱"。

V2 拆成 5 层架构 + tool/subagent/sandbox 三种 primitive 严格区分。**这是"加 tool 让 Agent 变差"的最具体的工程教训**——每个 Agent 项目都会撞上。

面试讲 Agent 演进 / 架构重构，这 5 个失败模式 + 5 层架构直接搬。

---

## V1 失败：5 个具体的"加 tool 让 Agent 变差"的 pattern

Sidekick 加了 N 个 tool 后踩的 5 个坑：

### 1. Tool selection 越来越不准

> "Similar tools with overlapping descriptions made it harder for the model to pick the right one."

**重叠 description 的 tool 让模型选择失败率上升**——不是"更多选择更好"，是"更多选择更难选"。

### 2. Tool definitions 吃 context

> "Supplying many schemas and instructions on every turn left less context for the user's request and the actual work data."

每 turn 都把所有 tool schema 塞 context → **剩下给"真正工作"的空间越来越少**。

### 3. Agent 太通用 → 单一 prompt 管所有域

> "A single prompt had to contain instructions for research, content generation, data analysis, board operations, file processing, and other domains."

一个 prompt 写 6 个 domain 的指令 → **每个 domain 的指令都不够具体**。

### 4. 长 workflow 容易断

> "A failure in one intermediate step could cause the entire reasoning loop to lose direction."

单 Agent 单 loop 的脆弱性——一个 step 失败 → 整个 loop 失去方向。

### 5. 测试组合爆炸

> "Adding one new tool could affect workflows that appeared unrelated to it."

**Tool N+1 加进去，所有现有 workflow 的 eval 都要重跑**——加 tool 是 O(N) 成本。

**加上**：Observability 难（fail 来自 planning / tool choice / tool execution / retrieved context / final response 中哪一个？）、Latency / cost 随复杂度线性增长、Tool exploration 不必要（Agent 自己乱试）。

**面试可讲角度**：这是 *capability vs reliability* 的反直觉关系。**加 tool = 加不确定性 = 减可靠性**。**Tool 不是越多越好**。

---

## V2 架构：5 层边界清晰

```
[monday.com UI / 上下文]
       ↓
[Layer 1: Context + Permission Layer]
  - 用户、account、workspace、board、document、dashboard、item
  - 检索 monday.com 数据 / semantic search / conversation / files / memories
  - 权限过滤（"不是附加安全，是基础要求"）
       ↓
[Layer 2: Orchestration Agent]
  - 理解用户意图、维护 plan、决定怎么执行
  - 简单任务直接答或调一个 tool
  - 复杂任务 → 委派 subagent 或用 sandbox
       ↓
[Layer 3: Subagents]
  - 狭窄目标 + 小 toolset
  - 例：content-generation agent 不需要 board-management tool
  - 隔离清晰、可独立评估
       ↓
[Layer 4: Tools]
  - 受控访问 monday.com 和外部系统
  - Bounded 操作（读 board / 搜文档 / 更新 item / 触发已知 action）
  - 3-tier classification + tiled tool discovery（菜单式，不一次给整本菜单）
       ↓
[Layer 5: Sandbox]
  - 复杂 + 迭代的工作（CSV 清洗 / 多步分析 / chart 生成）
  - 隔离文件系统 + 代码执行
  - 中间结果不进 main context
       ↓
[Observability + Evaluation Layer]
  - 全部 trace：model calls / tool calls / delegation / sandbox 活动 / latency / token / failures
  - Offline eval + production signals 双轨
```

**关键判断**：

> "**The real shift wasn't 'moving to multiple agents.' It was drawing clearer boundaries between planning, domain-specific reasoning, tool use, and execution.**"

不是"加更多 Agent"，是**划清边界**。

---

## Tool vs Subagent vs Sandbox 决策树

这篇文章工程价值最高的部分：

```
                    这个任务怎么做？
                          │
        ┌─────────────────┼─────────────────┐
        ↓                 ↓                  ↓
   bounded action   narrower reasoning   intermediate state
   明确输入输出       专注领域思考          会污染 main context
        │                 │                  │
        ↓                 ↓                  ↓
     [TOOL]          [SUBAGENT]          [SANDBOX]
   读 board / 改 item  risk analysis      CSV 清洗 / chart 生成
   搜文档 / 发消息     research / 写作     长时间分析
```

**3 种 primitive 的本质区别**：

| Primitive | 本质 | 输入/输出 | Context 隔离 |
|---|---|---|---|
| **Tool** | 受控访问 | 明确输入、明确输出 | 不隔离（main context 看到） |
| **Subagent** | 专门推理 | 任务 + 限制 toolset | **独立 context window** |
| **Sandbox** | 工作环境 | 文件 + 代码 + 迭代 | **独立文件系统 + 代码运行时** |

**典型工作流（混合使用）**：

```
User: "Analyze project data from 3 boards + attached CSV, identify delivery risks, prepare exec update."

1. Main orchestrator
   → 用 monday.com tool 检索 3 个 board 数据
2. Orchestrator 委派 risk analysis subagent
   → Subagent 独立 context，专注 risk analysis
3. Subagent 用 sandbox 处理 CSV
   → Sandbox 隔离文件系统，CSV / 中间 dataframe 不进 subagent context
   → Sandbox 返回 structured findings
4. Main orchestrator 或 writing subagent
   → 把 findings 写成 exec update
```

**3 种 primitive 在同一工作流里全部用上**——不是非此即彼。

**面试可讲角度**：这是 *orthogonal primitives* 的工程设计。**Tool 是"动词"，Subagent 是"主语"，Sandbox 是"工作台"**。一个工作流需要哪几个就用哪几个，**不要试图用一种 primitive 做所有事**。

**工程落地 checklist**：
- ☐ 给每个 task 标"tool / subagent / sandbox"——不要默认全用 tool
- ☐ **Tool 描述要 non-overlapping**——避免模型选择失败
- ☐ **Tool discovery 分层**——不是一次性给所有 schema，按 task 类型激活对应 tier
- ☐ Subagent 给**最小 toolset**（3-5 个 max），独立 context window
- ☐ Sandbox 只在"有大量中间状态 / 多步迭代"时启用——别滥用

---

## Observability + Evaluation：成功 ≠ 有用

> "Successful execution is not equivalent to a useful result. **We need to evaluate whether Sidekick selected the correct context, followed permissions, completed the task, and produced an answer the user could trust.**"

**4 个评估维度**：
1. 选的 context 对不对
2. 权限遵守了吗
3. 任务完成了吗
4. 答案可不可信

**不是**"API 调用成功率高"——那是基础设施指标，不是用户体验指标。

**面试可讲角度**：这是 *vanity metrics vs product metrics* 的 Agent 化。**Token 便宜 / latency 低 / tool call 成功率高**——这些都对，但**用户任务完成度 + 答案可信度**才是产品指标。**任何 Agent 项目都要有"任务完成度"这一条 metric**。

**工程落地 checklist**：
- ☐ 离线 eval：固定 scenario set，每次 prompt 改动跑一次
- ☐ 生产 trace：自动归类失败 mode（routing 错 / context 错 / tool 执行错 / 答案错）
- ☐ 任务完成度评分——不是"API 成功"，是"用户目标达到"
- ☐ 权限遵守 audit——trace 里专门标记 agent 是否访问了不该访问的资源

---

## 5 个 Lessons（直接讲简历里）

### Lesson 1：不要默认给一个 Agent 所有能力

> "More tools can make an agent less capable because they increase ambiguity and consume context."

**反面**：给 Agent 装 100 个 tool。**正面**：按需加载 + 最小 toolset。

### Lesson 2：Context 是架构的一部分

> "Retrieving information, filtering it through permissions, selecting what is relevant, and deciding what not to include are core system responsibilities."

**Context engineering 不是"加更多 RAG"**——是**架构层设计**：什么进来、什么过滤、什么留下、什么不收。

### Lesson 3：tool 用于 bounded action，sandbox 用于 open-ended work

> "Turning every operation into an API or MCP tool can create an enormous and inefficient interface."

**每个操作都包成 API** = 巨大低效的 interface。**用 sandbox 隔离"复杂 + 迭代"的工作**。

### Lesson 4：可观测性从第一天设计

> "Agent behavior is probabilistic, and successful API calls do not prove that the user's goal was achieved."

**Probabilistic 系统必须可观测**——success ≠ useful。

### Lesson 5：用户面前的简单 ≠ 内部简单

> "A request can feel like a conversation with one assistant while being executed by several specialized components behind the scenes."

**用户体验** = 一个 Assistant。**内部架构** = 5 层 + 3 primitive + 多 subagent + sandbox。**这是工程的价值**。

---

## 简历可直接借用的项目骨架（Agent 架构演进 / 内部 AI 助手类）

```
项目名：[业务名] AI 助手 / Sidekick（从 V1 单 Agent 到 V2 多层架构的重构）

角色：核心工程师 / AI Engineering Group Lead

V1 失败 → V2 重构故事（5 个失败模式 → 5 层架构 + 3 种 primitive 决策树）：
1. Tool selection 失败 → Subagent + 小 toolset
2. Tool 定义吃 context → 分层 tool discovery（菜单式）
3. 单 prompt 管多域 → 每个 subagent 专注一个域
4. 长 workflow 脆弱 → Orchestrator 委派 + sandbox 隔离
5. 测试组合爆炸 → 每个 subagent 独立 eval

5 层架构：
- Context + Permission Layer
- Orchestration Agent
- Subagents（窄目标 + 小 toolset）
- Tools（bounded action + 权限感知）
- Sandbox（隔离文件 + 代码 + 长时迭代）

3 种 primitive 决策树：
- Bounded action → Tool
- Narrower reasoning → Subagent
- Intermediate state heavy → Sandbox

可观测性 + 评估：
- 4 个评估维度：context / permission / task completion / answer trust
- Offline eval + 生产 trace 闭环

成果（量化）：
- Tool selection accuracy：[A]% → [B]%
- Task completion rate：[X]% → [Y]%
- Latency / cost：[P] → [Q]
- 新场景上线时间：[N] 周 → [M] 周
```

**面试常被问到的延伸问题**：
- "为什么不让一个 Agent 做所有事？" → **capability vs reliability 的反直觉关系**——加 tool 加不确定性减可靠性；单 Agent 不能 scale 多 domain
- "Subagent 怎么通信？" → **不直接通信**——通过 orchestrator 调度 + sandbox 文件共享
- "怎么决定用 tool 还是 subagent 还是 sandbox？" → **决策树**：bounded action → tool；narrower reasoning → subagent；intermediate state heavy → sandbox
- "Tool 太多怎么办？" → **tiled tool discovery**——按 task 类型激活对应 tier，不一次给所有 schema
- "怎么评估 Agent 真的有用？" → **4 维评估**：context / permission / task completion / answer trust——不是 API success

---

## 配套阅读

- **同主题重构**：[Paid Media Agent](blog/posts/2026-09-15-agent-paid-media-workspace-five-lessons.md) — LangChain 自家 GTM Agent 同样的"v1 单 agent → v2 多层"演进
- **multi-agent 路由**：[Lyft / Vodafone / LATAM](blog/posts/2026-09-15-cx-agents-five-patterns-production.md) — Supervisor + Use Case subagent 的另一组案例
- **底层 SDK**：[Claude Agent SDK](blog/posts/2026-09-15-claude-agent-sdk-engineering.md) — sandbox + hook + subagent 的 SDK 实现

参考资料：

- [Building monday.com Sidekick](https://www.langchain.com/blog/building-monday-com-sidekick-why-capable-agents-need-more-than-just-tools) — Omri Bruchim
- [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview)
- [LangSmith Sandbox](https://docs.langchain.com/langsmith/sandboxes)
