---
title: Madrigal Pharma 多 Agent 平台：医药数据的"看不见的归一化"+ Skills 联邦制 + Trace 反哺 Eval
date: 2026-09-15
tags: [Agent, 多 Agent, 医药 RAG, Deep Agents, 工程实践]
summary: 制药公司 Madrigal 用 LangChain / Deep Agents 搭多 Agent 平台，关键思想：把所有数据源归一化成一致的 tool interface（Agent 不关心数据从哪来）；modular skill 把单一用例变成平台；trace → eval dataset 是生产反馈的闭环。新用例从"几周"降到"几小时"。
source-url: https://www.langchain.com/blog/customers-madrigal
source-title: How Madrigal Built a Flexible and Scalable Multi-Agent Research and Intelligence Platform for Pharma
source-author: Parth Patel / Ron Filippo (Madrigal Pharmaceuticals)
---

## 引子

制药公司 Madrigal 几个月内把 LangChain / Deep Agents 搭成一个 multi-agent platform，**新用例上线时间从几周降到几小时**。不是靠更多人——靠 4 个工程决策：

1. **数据源归一化成 tool interface**（Agent 不关心数据从哪来）
2. **Skills 联邦制**（一个用例变平台的关键抽象）
3. **并行 subagent + 共享文件系统**（context 不爆，速度不慢）
4. **生产 trace 反哺 eval set**（regression test 自动生长）

面试讲 RAG / 多 Agent / 领域知识平台，这 4 条都能直接搬。

---

## 决策 1：数据源归一化成 tool interface——可扩展的根

制药公司的数据"散落各处"：

- 结构化系统（临床数据 / 监管数据库）
- 非结构化文档（论文 / 内部报告）
- 外部源（PubMed / FDA / 临床试验注册库）
- 实时 API（公司 ERP / Salesforce）

**每个 source 格式、访问模式、访问预期都不一样**。

Madrigal 的解法：

> "We solved this by making the differences invisible to the agents. **No matter where data comes from, it is normalized, stored in the same secure data warehouse, and made accessible through a consistent tool interface.** From the agent's perspective, it's all just information it can use."

**关键思想**：

```
[数据源 A]  ↘
[数据源 B]  →  [归一化 pipeline]  →  [统一 warehouse]  →  [tool interface]  →  [Agents]
[数据源 C]  ↗
```

- **Orchestrator 不需要知道每个 domain 的细节**——它只调度
- **Agent 不需要写"如果从 A 取就...从 B 取就..."的分支**——所有 source 看起来一样
- **新加一个 source 只需要改归一化层**——Agent 不动

**面试可讲角度**：这是 *adapter pattern* 的 Agent 化。**任何"对多源系统"的访问都该用 adapter 隔离**——adapter 的稳定性决定了上层 Agent 的可扩展性。**别让 Agent 处理 source-specific 逻辑**。

**工程落地 checklist**：
- ☐ 设计"tool interface schema"——所有数据源必须符合这个 schema，Agent 只看 schema
- ☐ 每个 source 写一个 adapter（归一化 + cache + 权限过滤），不直接让 Agent 调原始 API
- ☐ Orchestrator 只调度，不直接读 source——通过 subagent 间接读
- ☐ 加新 source = 加新 adapter + 注册到 registry，**不改 Agent 代码**

---

## 决策 2：Skills 联邦制——单一用例变平台的关键

> "Instead of hardcoding logic, we introduced modular capabilities based on Anthropic's skills approach. **Each skill defines how to approach a type of problem: what to look for, how to reason about it, what good output looks like.** The orchestrator simply loads the right skill at the right time. That means adding a new use case doesn't require rebuilding the system. It just requires defining a new way of thinking."

**关键设计**：
- **Skill 不是"工作流脚本"**——它是"思考方式"（how to approach this class of problem）
- **Orchestrator 按任务加载 skill**——不写死
- **新用例 = 新 skill**——不写新代码

**这和 Stripe Kai 的 skills 联邦制、Klarna 的 workflow 模板化是同一个思想**——**把"业务知识"和"系统逻辑"解耦**。

**面试可讲角度**：这是 *plugin architecture* 的 Agent 化。**不要在 Agent 代码里硬编码业务流程——把业务流程表达成 skill**。Skill 是"如何思考这种问题"，不是"如何执行这种步骤"。**Skill 让 domain expert 能直接贡献系统能力**，不用通过工程师。

**工程落地 checklist**：
- ☐ Skill 结构化（frontmatter + instructions + tools 清单 + examples）
- ☐ Skill 进版本管理（CI/CD review）
- ☐ Orchestrator 按 task 描述动态选择 skill
- ☐ Domain expert 能独立写 skill（不被工程 release cycle 阻塞）

---

## 决策 3：并行 subagent + 共享文件系统

**问题**：复杂研究任务涉及多个角度（query 多个 source、分析多个 dimension）——串行做太慢。

**Madrigal 的解法**：

```
[Orchestrator Agent]
       ↓ 拆 3 个 sub-task
[Subagent A: source 1 分析]  ↘
[Subagent B: source 2 分析]   → [共享文件系统]  → [Orchestrator 汇总]
[Subagent C: source 3 分析]  ↗
```

**两个关键设计**：

### Subagent 自己也并行

Subagent 不是单线程——它内部还会并行 query 自己负责的多个 dataset。**"orchestrator 把任务并行化，subagent 也并行化"**——双层并行。

### 共享文件系统做 memory

> "**Every result is stored. Every source is tracked. Every intermediate step is available for reuse.** Instead of passing information directly between agents, everything flows through this shared layer—keeping coordination simple even as the system scales."

**为什么要文件共享而不是 message passing**：
- 100 个 source 分析完，每个都 1MB——message 传递会让 orchestrator context 爆
- 文件系统是 Agent 已经理解的原语（reason about files / directories / scripts）
- 失败恢复容易——subagent 中途挂掉，结果还在文件系统里，新 subagent 接着干

**面试可讲角度**：这是 *shared memory* vs *message passing* 的经典工程取舍——**当 subagent 多 / 数据大时，文件共享比消息传递更可扩展**。**这是 Deep Agents 的 filesystem middleware 直接提供的原语**——用现成的。

**工程落地 checklist**：
- ☐ Subagent 之间不直接通信——通过文件系统共享 intermediate result
- ☐ 每个 subagent 写到自己的命名空间（`/sandbox/<task_id>/<subagent_id>/`），避免冲突
- ☐ Orchestrator 只读 manifest / summary，**不读**每个 subagent 的全量 result
- ☐ 双层并行：orchestrator 并行调度 subagent，subagent 内部也并行 query

---

## 决策 4：Trace → Eval dataset 自动闭环

Madrigal 最关键的一段：

> "**The part that's made the biggest ongoing difference: production failures feed back into our LangSmith datasets automatically. Every meaningful error becomes a new test case. The eval suite grows from real failures, not synthetic scenarios.**"

**Trace-driven eval 增长**：

```
[Production Agent run]
       ↓ (failure detected)
[LangSmith trace 自动归档]
       ↓ (error classifier 标 failure mode)
[加入 LangSmith dataset]
       ↓ (下次 eval 必跑)
[Regression test 自然长出]
```

**为什么这条最关键**：
- **Synthetic test cases 不能覆盖真实 edge case**——你不知道用户会怎么问
- **Production failures 是最真实的 regression signal**——它们告诉你"模型在这一类问题上真的会犯"
- **Eval set 自动长出**——不需要人工维护测试集

**面试可讲角度**：这是 *self-healing test suite* 的工程化。**你的 eval set 应该从生产数据自动增长，不应该靠工程师手动加**。**这是 LangSmith / Deep Agents 的关键能力，不要浪费**。

**工程落地 checklist**：
- ☐ Production trace 100% 归档（不只是 failure，success 也归档——将来可以做 fine-tuning）
- ☐ Failure 自动 classifier 标 mode → 加入 eval dataset
- ☐ 每次 prompt / workflow 改动 → 跑一次 eval set → 确认没退化
- ☐ 成功的 trajectory 进 fine-tuning 数据池（模型持续改进的原料）

---

## 简历可直接借用的项目骨架（多 Agent 知识平台 / RAG 类）

```
项目名：[领域] 多 Agent 研究 / 智能平台

角色：核心工程师 / AI 平台 Tech Lead

核心架构：
- Orchestrator Agent（拆解任务 + 调度 subagent）
- N 个 Subagents（按数据源 / 业务域隔离）
- 数据层：[N] 个 adapter 把异构 source 归一化成统一 tool interface
- 共享文件系统：subagent 间通信 + 中间状态持久化

4 个关键工程决策：
1. Adapter pattern：所有数据源走归一化 tool interface，新 source 不改 Agent
2. Skill 联邦制：业务专家写 skill 表达"如何思考"，Orchestrator 按任务加载
3. 双层并行 + 文件共享：orchestrator 并行调度 subagent，subagent 内部并行 query；subagent 间用文件共享而不是 message passing
4. Trace → Eval 闭环：production failure 自动进 eval dataset，eval set 从真实问题增长

成果（量化）：
- 新用例上线时间：[N] 周 → [M] 小时
- 用例数量：[A] → [B]
- 团队规模：[X] 人维护
- 准确率：[C]%（LLM-as-judge + human review）
- 引用准确率：[D]%（RAG citation correctness）
```

**面试常被问到的延伸问题**：
- "数据源归一化怎么做？" → **adapter pattern**，每个 source 一个 adapter 写归一化 + cache + 权限过滤，Agent 只看统一 schema
- "Skill 怎么防止失控？" → **skill 进 CI/CD review**，domain expert 写但工程师 review；skill description 要 narrow + specific
- "为什么 subagent 用文件系统而不是消息？" → **数据量大 + subagent 多 + 失败恢复**——文件比 message 可扩展
- "eval set 怎么不让人工维护？" → **production failure 自动归类入 dataset**，classifier 标 failure mode，新 failure 进 regression suite
- "怎么 trace agent 决策？" → **LangSmith trace**——所有 tool call / retrieved chunk / agent decision 可见，按 session ID 关联

---

## 配套阅读

- **同架构同思想**：[Stripe Kai](blog/posts/2026-09-15-stripe-kai-one-engineer-one-week.md) — 同样用 Deep Agents + skills 联邦制做的内部平台
- **联邦 skill 思想**：[Klarna](blog/posts/2026-09-15-klarna-customer-support-multi-agent.md) — 早期 CX Agent 案例的 meta-prompting
- **trace 驱动**：[LATAM Compass](blog/posts/2026-09-15-cx-agents-five-patterns-production.md) — 对话转结构化 BI 的另一案例

参考资料：

- [Madrigal Customer Story](https://www.langchain.com/blog/customers-madrigal) — Parth Patel, Ron Filippo
- [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview)
- [Agent Skills 规范](http://agentskills.io)
