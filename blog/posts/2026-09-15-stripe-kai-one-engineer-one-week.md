---
title: Stripe Kai：1 个工程师 + 1 周，用 Deep Agents 搭全公司 Agent——3 个工程决策 + 简历级骨架
date: 2026-09-15
tags: [Agent, Deep Agents, Stripe, 内部平台, 工程实践]
summary: Stripe Knowledge AI Platform（Kai）从 296 用户涨到 5000+（4 周），83% 员工每周用，1 个工程师 1 周做出 MVP。3 个关键决策：把 Deep Agents 当 OS 而非工具、S3 虚拟文件系统 + sync in/out、agent skills 按 user profile 动态加载。附完整简历项目骨架。
source-url: https://www.langchain.com/blog/how-stripe-built-their-knowledge-ai-platform-on-deep-agents
source-title: How Stripe Built Kai, its Company-Wide AI Agent, on Deep Agents
source-author: Sofia Sulikowski (LangChain)
---

## 引子

Stripe 全公司 Agent "Kai"——一个工程师（Anupam）一周搭出 MVP，preview 一周打到季度目标，4 周从 296 用户涨到 5000+，现在 83% 员工每周用。**不是堆人，是靠 3 个正确的工程决策**。

这篇文章不是讲 Stripe 多牛，是讲**为什么 Deep Agents 让一个工程师能一周做出一个全公司 Agent 平台**——以及你自己做内部 Agent 项目时哪些决策可以照搬。

---

## 决策 1：把 Agent Harness 当 OS，而不是工具集

Stripe 早期发现：每个团队都在自己 Ruby / Java 栈上搭 Agent orchestration layer。**连通性简单，可靠性难**。Claude Code 2024 年底发布后，每个员工都想搭 Agent，但 terminal + 数据访问 + 安全是巨大 barrier。

Stripe AI Platform 团队的判断：**反过来走**——不把非技术员工推向 developer tooling，而是给一个"always-on, production-ready assistant"。这就是 Kai。

**架构 4 层（从上到下）**：

```
[Kai UI]                 ← 员工看到的 chat 界面
[Configuration layer]    ← 各团队配置专用 Kai 实例（不同 skill / 行为）
[Stripe-specific harness] ← Stripe 安全 / infra / 内部服务集成
[Deep Agents]            ← LangChain 开源 agent harness（处理 LLM 通信原语）
```

**关键判断**：Deep Agents 解决所有 **non-Stripey 问题**（tool-calling loop、middleware composition、streaming、state management），Stripe 团队**只解决 Stripey 问题**（security、infra、内部数据）。

**面试可讲角度**：这是 *platform vs product* 的工程取舍。**不要重新发明 agent 框架——选一个 harness 在上面建**。**底层 OS 你不需要懂，也不需要自己写**。Stripe 十几年的 Ruby/Java 基建在 Python-native Agent 上重新搭了一遍，但回报是 1 周 MVP。

**工程落地 checklist**：
- ☐ **不要从零搭 agent harness**——用现成的（Deep Agents / LangGraph / Claude Agent SDK），省几个月工程
- ☐ 把"业务特定逻辑"和"agent 通用机制"分层——前者快速迭代，后者稳定不变
- ☐ 配置层和数据层分离，让业务团队**自助配置 Agent 实例**而不用碰底层代码

---

## 决策 2：S3 虚拟文件系统 + sync in/out 解决"持久化 sandbox"

Kai 不是 local process——是 cloud production service。**Anupam 解决的核心难题：怎么让 Agent 看到一个 persistent file environment**。

**答案**：自己实现一个 S3-backed virtual filesystem，Deep Agents 的 filesystem middleware 包它。

**Sync in/out 模式**：

```
[Agent 在 sandbox 外跑 LLM loop]
        ↓ 调用 sandbox.execute(...)
[sandbox 内 microVM]
  1. sync-in：把当前 session 相关的文件从 S3 拉到 microVM
  2. 执行 agent 写的 Python
  3. sync-out：把修改 / 新增的文件写回 S3
        ↓ return result
[Agent 继续 LLM loop]
```

**关键设计**：
- **Sandbox 是 Agent 的 tool，不是 Agent 的 execution environment**——Agent 本身在 sandbox 外，调用 sandbox 跑 Python
- **避免 lethal trifecta**（LLM-generated code + sensitive data access + external communication 三个同时具备）——执行边界清晰
- **Summarization middleware** 管多 turn 长 session——threshold / summarizer model / output size 几个 knob 调清楚，**避免 cache miss 烧钱**

**面试可讲角度**：这是 *separation of concerns* 在 Agent 时代的版本。**LLM 是控制平面，sandbox 是数据平面，两者通过 tool call 解耦**。**Agent 不能"在 sandbox 里"——必须"调用 sandbox"**——这是安全边界。

**工程落地 checklist**：
- ☐ Sandbox 实现为 Agent 的 tool，不让 Agent 直接在 sandbox 里执行（保持 Lethal Trifecta 边界）
- ☐ 持久化用 cloud storage（S3 / GCS）+ sync in/out 模式，**不要**让 sandbox local FS 当持久层
- ☐ 多 turn session 必备 summarization middleware（threshold + summarizer model + output size 三参数调清楚）

---

## 决策 3：Skills 联邦制 + 动态加载 500+ 内部 MCP 工具

Stripe 内部有 **500+ MCP 工具** + **1000+ skills**。Agent 不可能加载所有。

**Skills 是 Deep Agents 的结构化模块**——每个 skill 定义"怎么完成一类任务 + 用什么工具 + 怎么思考"。Stripe 的设计：

- **联邦制**：每个 team 自己维护自己的 skills
- **基础 Kai** 装一组导航类 skills（cross-Stripe 通用）
- **按 user profile 加载 tiered skills**（sales-ops 和 finance 拿不同 skill set）
- **个人级 profile** 还可加额外 skill

**500+ MCP 工具的动态加载**：

```
[Agent]
  ↓ 需要新能力
[Skill 选择]（AgentSkills allowedTools）
  ↓ 根据 skill 描述选
[加载对应 MCP 工具定义]
  ↓ (而不是全量加载 500+ 工具)
[Tool execution]
```

**关键经验**：模型在 150 skills + system prompt 之上会质量下降（1024 字符 frontmatter 限制）。Stripe 现在的方案是**纯 LLM 选择（小规模更好）** + 未来 RAG / classifier 预过滤（大规模必需）。

**面试可讲角度**：这是 *just-in-time loading* 应用到 Agent context。**不要把所有工具 / skills 塞 context——按需发现、按需加载**。和 Claude Agent SDK 里的 `defer_loading`、Anthropic Advanced Tool Use 里的 Tool Search Tool 是同一个思想。

**工程落地 checklist**：
- ☐ Skills 用渐进披露（skill description 先全量，完整指令按需加载）
- ☐ 工具按 skill 选择**反向加载**（不是正向定义"每个 skill 用哪些 tool"）
- ☐ **Pin 关键 skills**——不能被模型动态卸载（policy、合规、上下文必备）
- ☐ Profile-based skill set——不同角色拿不同默认 skill
- ☐ 监测"skill 选择准确率"——如果 < 90%，加 RAG / classifier 预过滤层

---

## 3 个业务决策（不是工程决策）

### 1. 不强推 AI 给所有人，而是 meet them where they are

> "We had a lot of people who said, 'I found the previous thing unapproachable. I had to tune a bunch of knobs. But I was being asked to use AI, and I really tried.' And then: 'this is great, I don't have to do any of that stuff.'"

Kai 不是"自助 AI 工具"，是**生产级 always-on assistant**。用户**不需要调任何 knob**——这是产品决策，但工程上意味着配置层必须能扛住所有"用户差异"。

### 2. 把内部知识变成平台资产

> "1000+ skills from 100+ teams"

Stripe 让每个团队把自己的 domain knowledge 贡献成 skill——**这不是 engineering 团队的工作，是业务团队的工作**。**平台的价值 = 联邦 skill 的数量**。

### 3. Adoption 是产品 / 工程的双胜利

Kai 4 周涨 16 倍，季度目标一周达成。**关键是 GTM / Marketing 95% 用、Engineering 反而用得更多**——这是产品/工程的胜利，不是 GTM 团队的胜利。

---

## 简历可直接借用的项目骨架（内部 AI 平台 / 知识 Agent 类）

```
项目名：[公司名] Knowledge AI / 内部 Agent 平台

角色：核心工程师 / Tech Lead

核心架构（4 层）：
- UI 层：chat 界面 + 持久化 session
- 配置层：不同部门 / 角色配置不同 Agent 实例
- 业务 harness：[合规 / 安全 / 内部服务集成]
- Agent harness：[Deep Agents / LangGraph / Claude Agent SDK]

3 个关键工程决策：
1. 底层 agent harness 选现成的（不重新发明），业务层只解决领域问题
2. Sandbox = tool（不是 execution env），通过 cloud storage + sync in/out 实现持久化
3. Skills 联邦制 + 按 profile 动态加载；tools 按 skill 选择反向加载

3 个业务决策：
1. 用户零配置——产品体验做到"不需要调 knob"
2. 内部知识联邦化——每个团队贡献 skill，平台聚合
3. Adoption 指标驱动（DAU / WAU / session 数）

成果（量化）：
- 上线时间：[N] 周（突出 1 周 MVP 的速度）
- 用户增长：[A] 用户 → [B] 用户（[X] 周内）
- 周活率：[Y]% 员工每周使用
- 业务覆盖：营销 [M]% / GTM [K]% / 工程 [P]%
- 维护成本：[Q] 个工程师维护
```

**面试常被问到的延伸问题**：
- "为什么不用现有 chatbot 框架？" → **chatbot 不是 Agent**——chatbot 是 question-answering，Agent 是 task-completing；前者给答案，后者给 artifact（报表 / chart / 分析）
- "Sandbox 怎么解决 lethal trifecta？" → **Sandbox 是 tool，不是 execution env**——Agent 不在 sandbox 里跑，调用 sandbox 跑 Python
- "1000+ skills 怎么 scale？" → **Profile-based tiered loading** + skill selection gating tool context + 未来 RAG/classifier 预过滤
- "非工程师怎么贡献 skill？" → **Skill 是结构化模块**——每个 team 写自己领域的 skill 进版本管理，CI/CD 自动 review + 部署
- "Python 重写的 ROI 怎么算？" → **1 周 MVP 击中季度目标**——这是 Python-native agent harness 投入的 payback

---

## 配套阅读

- **同 harness 不同业务**：[Madrigal Pharma Agent](blog/posts/2026-09-15-madrigal-pharma-multi-agent-platform.md) — 同一 Deep Agents 用法在医药领域的另一案例
- **底层 SDK**：[Claude Agent SDK](blog/posts/2026-09-15-claude-agent-sdk-engineering.md) — sandbox + hook + subagent 的 SDK 实现
- **架构演进**：[Paid Media Agent](blog/posts/2026-09-15-agent-paid-media-workspace-five-lessons.md) — LangChain 自家 GTM Agent 用同一思路搭的

参考资料：

- [How Stripe Built Kai](https://www.langchain.com/blog/how-stripe-built-their-knowledge-ai-platform-on-deep-agents) — Sofia Sulikowski, LangChain
- [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview)
- [Agent Skills 规范](http://agentskills.io)
