---
title: Klarna AI Assistant：85M 用户、70% 自动化、80% 解决提速——3 个早期 multi-agent 工程决策
date: 2026-09-15
tags: [Agent, Klarna, LangGraph, 早期 multi-agent, 工程实践]
summary: Klarna AI Assistant 用 LangGraph + LangSmith 服务 85M 月活用户，70% 重复任务自动化、解决时间 -80%、效果等同 700 个全职员工。3 个早期 multi-agent 决策：controllable routing、context-aware dynamic prompt、test-driven prompt iteration。LangChain 因此设计了 meta-prompting。
source-url: https://www.langchain.com/blog/customers-klarna
source-title: How Klarna's AI assistant redefined customer support at scale for 85 million active users
source-author: LangChain Team
---

## 引子

Klarna AI Assistant 服务 **85 million 月活用户、250 万日交易**——把 **70% 重复支持任务自动化**、**解决时间 -80%**、效果等同 **700 个全职客服**。这是 LangChain 生态**最早一批大规模 multi-agent 生产案例**之一（2025 年 2 月）。

面试讲 CX Agent / 早期 multi-agent 演进 / 客服 Agent，这篇文章给的 3 个工程决策都是教科书级别。

---

## 决策 1：Controllable agent routing——延迟、可靠性、成本三赢

Klarna 用 **LangGraph** 搭 multi-agent 系统，**路由可控**（controllable routing）：

- 不同任务走不同 path（payment / refund / escalation）
- Routing 决策可解释、可追溯、可优化
- **降低 latency**（不像 single-agent loop 那样乱试 tool）
- **提升 reliability**（路由错了能明确知道哪一步错）
- **降低 operational cost**（少了重复 tool call）

**早期 multi-agent 的核心原则**：

> "**Don't let one agent do everything. Make routing deterministic and observable.**"

**面试可讲角度**：这是 *controlled dispatch* 的工程化。**Multi-agent 的价值不只是"分工"，是"路由可控"**——路由错了立刻知道哪步错，单 agent loop 错了要在 trace 里找半天。

---

## 决策 2：Context-aware dynamic prompt——按场景调 prompt

Klarna 用 **dynamic prompt tailoring**（按场景调 prompt）：

- 不是一套 prompt 打天下
- 按 task type / user state / historical context 调 prompt
- **Token cost 下降、latency 下降、relevance 上升**

**核心模式**：

```
[User request + context]
       ↓
[Task classifier]
       ↓
[Select prompt template for this task type]
       ↓
[Inject context (user history / state)]
       ↓
[LLM call]
```

**面试可讲角度**：这是 *prompt engineering as code* 的早期形态。**Prompt 不该是 string literal——该是 templated + parameterized + context-aware**。**同一个 Agent 在不同场景下应该用不同 prompt**，**不是把所有指令塞一个 prompt**。

**对比**：和 Paid Media Agent 的 5 层 context 分层、Sunday Sidekick 的 layered architecture 是同一思想——**不要把所有上下文塞一个 prompt**。

---

## 决策 3：Test-driven prompt iteration——把 prompt 当代码迭代

Klarna 用 **LangSmith** 做 test-driven prompt development：

1. **记录每一步行为**——step-by-step trace（不是只有 input/output）
2. **抓 critical use cases**——高频 / 高风险场景
3. **LLM-as-judge 评分**——自动 eval
4. **Prompt 迭代**——基于 eval 结果改 prompt
5. **回归测试**——每次 prompt 改动跑同一组 scenario

**关键工程**：

> "Leveraging LangSmith, Klarna rigorously tested critical use cases for their AI assistant, then validated and refined agent performance with **LLM evaluations** and prompt iteration."

**这一步直接催生了 LangSmith 的 meta-prompting 功能**：

> "Klarna helped inspire and design advanced capabilities like **meta-prompting**. Meta-prompting allows users to suggest specific improvements to the prompts, by prompting them and seeing how the optimized prompt impacted response quality."

**面试可讲角度**：这是 *prompt as code* 的早期成熟形态。**Prompt 改动要像代码改动一样有 test、有 eval、有 regression**。**LangSmith 的 meta-prompting 能力直接来自 Klarna 的工程实践**——开源工具的核心能力往往来自真实生产反馈。

---

## 成果数字（直接抄到简历）

```
70%      重复支持任务自动化
80% ↓    平均解决时间下降
= 700 FTE 等效人力
2.5M     已处理对话数
85M      月活用户
```

---

## 简历可直接借用的项目骨架（客服 / CX Agent 类）

```
项目名：[公司名] AI 客服 / CX Agent 平台

角色：核心工程师 / AI Lead

3 个关键工程决策：
1. Controllable multi-agent routing：每个 task type 独立 path，路由可解释
2. Context-aware dynamic prompt：按场景调 prompt，token cost + latency 双降
3. Test-driven prompt iteration：trace + LLM-as-judge + regression test 三件套

工具栈：
- LangGraph（controllable state machine）
- LangSmith（trace + eval + dataset）

成果（量化）：
- 自动化率：[A]% 重复任务
- 解决时间：[X]% ↓
- 等效人力：[N] FTE
- 覆盖用户：[M] 月活
```

**面试常被问到的延伸问题**：
- "Multi-agent routing 怎么设计？" → **task classifier 先决定走哪条 path**——path 可观察、可优化、可 debug
- "Prompt 怎么管理？" → **prompt template 按场景分类 + versioned + parameterized**——不要一个 string literal 打天下
- "Prompt 改动怎么知道没退化？" → **eval dataset + LLM-as-judge + regression test**——每次改动跑同一组 scenario
- "LangSmith 怎么帮上忙？" → **trace 让 routing 错误可定位**，eval 让 prompt 改动可量化

---

## 配套阅读

- **同主题更新版**：[CX Agents Lyft / Vodafone / LATAM](blog/posts/2026-09-15-cx-agents-five-patterns-production.md) — 2026 年最新的 CX Agent 演进
- **架构演进**：[Sidekick](blog/posts/2026-09-15-agent-sidekick-bounded-responsibilities.md) — 单 Agent → 多层架构的演进路径
- **底层框架**：[3 Years of Graph Engineering with LangGraph](blog/posts/2026-09-15-langgraph-three-years-patterns.md) — LangGraph 的设计哲学

参考资料：

- [Klarna AI Assistant](https://www.langchain.com/blog/customers-klarna) — LangChain Team
- [LangGraph](https://www.langchain.com/langgraph)
- [LangSmith](https://www.langchain.com/langsmith)
