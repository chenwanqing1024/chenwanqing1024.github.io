---
title: CX Agent 生产实践：Lyft / Vodafone / LATAM 三家 5 个共同模式 + 简历级项目骨架
date: 2026-09-15
tags: [Agent, CX, 多 Agent, LangGraph, 工程实践]
summary: 把 LangChain 三家 CX 客户案例（Lyft 65% deflection + 35% resolution、Vodafone 90% 正确率 + 82% resolution、Concierge 13% → 1% out-of-scope）抽出 5 个跨企业可复用的工程模式，每个模式给定位 + 数据 + 工程提示 + 简历项目骨架。
source-url: "https://www.langchain.com/blog/customer-experience-cx-agents-in-production-lessons-from-lyft-vodafone-and-latam-airlines"
source-title: "CX Agents in Production: Lessons from Lyft, Vodafone, and LATAM Airlines"
source-author: Jess Ou (LangChain)
---

## 引子

Lyft 每月 270K AI Assist 对话、65% deflection、35% resolution；Fastweb + Vodafone 的 Super TOBi 服务 950 万用户、90% 正确、82% resolution；LATAM Concierge 13% → 1% out-of-scope。这些不是 PR 数据——它们对应具体的工程决策。**这篇文章抽 5 个跨企业复用的模式**，每个都给数据 + 工程落地 + 简历项目骨架。

面试讲 CX Agent 项目，这 5 条都能直接搬。

---

## 模式 1：自服务化平台是规模化前提（Lyft）

**一行定位**：当一个公司有 N 个 support / 业务场景时，**不能每个 Agent 都让 ML 工程师写**——必须有"运营 / PM / 领域专家能自己起一个新 Agent"的平台。

Lyft 的演进：
- **V1**：ML 工程师手写每个 Agent，第一个 driver Agent 用 **6 个月**
- **V2**：平台化后，新 configurable Agent **2 周**
- 关键差异：**Configurable Agent 用 JSON 配置 + LangSmith Prompt Hub 的 prompt**，领域专家自己写，不用工程师

**工程关键**：
- 把"业务意图"和"工程实现"解耦——领域专家写 prompt + JSON schema，工程师提供 platform
- **Prompt Hub 版本化**：所有 prompt 进版本管理，diff 可追溯
- **Configurable vs Specialized 两层并存**：高风险复杂场景（damage claim 含图片 + fraud detection）继续由 ML 工程师写，标准场景（账户查询、退款）由运营配置

**面试可讲角度**：这是 *self-service infra* 的 Agent 化。**任何"被反复提的需求"，都该被平台化抽象出来**——不是给更多人手，是给非工程师自助能力。

---

## 模式 2：Evaluation 是 shared language（Lyft）

Lyft 开放 Agent 给非工程师后，**真正的瓶颈不是平台，是 prompt 质量和评估标准**。他们建了一整套 evaluation flywheel：

### Pre-launch：simulation + rubric

```
simulated_user (LLM role-play) ↔ agent
         ↓
trajectory: messages + tool calls + state changes
         ↓
rubric scoring:
  - code-based assertion (concession / escalation 正确)
  - LLM-judge (educational content 是否合适)
```

**关键工程细节**：
- **模拟用户必须调校**——Lyft 早期模拟用户太"礼貌"（pass rate 90% 但生产表现差），后来 fine-tune 在真实用户 verbatims 上，加 persona（refund seeker、AI skeptic、想找人类的人）
- **Rubric 要 narrow + behavior-specific**——不要"回答 helpfulness"这种通用指标，要"重复教育内容 > 3 次就 fail"这种具体行为规则
- **Pass/fail 比 scalar score 更有效**——binary 结果直接对应一个具体的修复动作

### Post-launch：trace → annotation queue → dataset

```
production trace
    ↓ (failure detected)
annotation queue（PM + QA 标注）
    ↓ (labeled with failure mode)
LangSmith dataset
    ↓ (auto-fed into next eval run)
regression-tested prompt / workflow change
```

**关键工程细节**：
- **生产失败自动入 eval 集**——这是 evaluation flywheel 闭合的关键
- 成功的 trajectory 还能作为 fine-tuning 数据，未来还能训基础模型
- LLM judge 必须**和人类 reviewer 校准**——定期抽样对比，agreement rate 不够就调整 judge prompt

**面试可讲角度**：这是 *CI/CD for prompts*。**prompt 改动要像代码改动一样跑 regression test**——你的 eval set 就是 prompt 的 test suite。**生产数据反哺 eval 集**才是 flywheel 闭合。

---

## 模式 3：Supervisor + Use Case subagents + structured action tags（Vodafone）

Fastweb + Vodafone 的 Super TOBi 架构：

```
[Supervisor Agent]
   ↓ 路由 + guardrail + shaping
[Use Case Agent 1: 账单]   ↘
[Use Case Agent 2: 漫游]    ↘  tool calls + structured action tags
[Use Case Agent 3: 销售]    ↗
[Use Case Agent N: ...]     ↗
   ↓
[结构化动作标签] → 直接调交易 API（激活 / 停用 / 改支付）
```

**两个关键设计**：
1. **Supervisor 用 LLM Compiler 模式**——决定调用哪些 API、按什么顺序执行、最后怎么生成回答
2. **结构化 action tags**：Use Case Agent 不仅返回自然语言，还能返回 action tag，让对话直接变成交易（"激活 offer / 禁用服务 / 更新支付方式"）

**Fastweb + Vodafone 用 Neo4j 存业务流程图**：

```
procedure.md → LangGraph 解析 pipeline
            → 提取步骤 / 条件 / action / API 依赖
            → 写入 Neo4j 知识图谱（步骤 ↔ 条件 ↔ action ↔ API）
            → CI/CD 部署，小时级更新
```

**当 consultant 提问时**：
- Supervisor 判断是结构化 troubleshooting 还是开放性问答
- Troubleshooting → 检索 Neo4j procedure → 逐步调用 API 测条件 → 命中即给 action
- 开放问答 → vector store + Neo4j 混合检索 → 答案带源引用

**核心数字**：**One-Call Resolution > 86%**。

**面试可讲角度**：这是 *LLM Compiler pattern* + *knowledge graph as procedural memory*。**业务知识（步骤、条件、action）不要写在 prompt 里，写在图数据库里——可更新、可审计、可被多个 Agent 共享**。**CI/CD 流程让业务专家能直接更新知识**。

---

## 模式 4：从生产 trace 重新设计架构（LATAM）

LATAM Concierge 早期用 triage agent：每个 specialist 自己 format 自己的输出。

LangSmith trace 揭穿了一个隐藏成本：**~15% latency + token overhead 来自"每个 specialist 重复结构化"**。

**重构后**：supervisor 保留最终输出权，所有 specialist 只返回 raw findings，supervisor 在最后一步统一 format。

**结果**：**cost 降 15%，quality 不变**。

**另一个 trace 揭穿的故事**：13% out-of-scope 看起来是用户在乱问——**实际 trace review 发现 95% 是真实需求（check-in / 行李 / LATAM Pass），只是 Agent 没设计来 handle**。**加一个 customer-care specialist，out-of-scope 13% → 1%，return rate 提升 6%**。

**面试可讲角度**：**架构问题经常不会出现在 aggregate dashboard 上，只出现在 trace 里**——你必须看 trace 才能找到。这是 *observability-driven architecture*。

**工程落地 checklist**：
- ☐ **不要等"复盘会"才发现架构问题**——每周抽 20 条 trace 看，找到一个真实低效 pattern 立即重构
- ☐ 关注"看起来合理但实际没必要的步骤"（重复 format / 重复 retrieve / 重复 validate）
- ☐ Out-of-scope / failure cluster 是 roadmap 信号，不是 bug

---

## 模式 5：对话本身是 business intelligence（LATAM Compass）

LATAM 做了 Compass——一个 ontology-driven pipeline，把**非结构化对话**（agent、UX research、call center、legal）转成**结构化知识**（BigQuery Graph）：

```
[非结构化源] → parser → Gemini mapper（按 ontology 抽实体关系）→ modeler → BigQuery Graph
                                  ↑
                         ontology registry（领域 schema）
                                  ↓
                         evaluation layer（抽得对不对）
```

**3 个关键设计**：
1. **Ontology 是真正的资产**——model 可换、pipeline 可升级，ontology 包含"我们关心什么、概念怎么关联"
2. **同一 pipeline 换 ontology 支持不同用例**——UX research（pain points / feature requests / user segments）、legal（parties / clauses / obligations）
3. **生态系统现实 > 技术纯洁性**——LATAM 评估了 Spanner Graph（更适合图查询），但因为其他数据全在 BigQuery，**改用 BigQuery Graph**——少一个 federated query 依赖

**结果**：UX research 从几周降到几天，每文档处理成本 ~1 美分。

**面试可讲角度**：这是 *conversations as first-class data product*。**Agent 产出的对话不是"日志"——是结构化的业务信号**。每条对话都包含 intent、preference、context、future need——这些是传统 BI 拿不到的。

**延伸**：Compass 后续会把 Concierge（出行前）+ call center（出行中）+ 出行后反馈串成 shared graph，**每个 agent 都能用上其他 agent 的洞察**。

---

## 5 个跨企业模式汇总

| # | 模式 | 数据点 | 工程核心 |
|---|---|---|---|
| 1 | 自服务化平台 | 6 月 → 2 周 | 业务意图 / 工程实现解耦 |
| 2 | Eval 是 shared language | 90% pass → 真实生产通过率 | rubric + simulation + production 反哺 |
| 3 | Supervisor + subagents + graph | 90% 正确、82% resolution | LLM Compiler + 知识图谱存流程 |
| 4 | Trace 驱动架构演进 | 15% cost 降、out-of-scope 13%→1% | 每周抽 trace 看，找到 pattern 立即重构 |
| 5 | 对话是 BI 资产 | UX research 周 → 天 | ontology-driven pipeline + graph store |

---

## 简历可直接借用的项目骨架（CX Agent 类）

```
项目名：智能客服 / CX Agent 平台

架构：
- Supervisor Agent（路由 + guardrail + 输入校验）
- N 个 Use Case Subagents（每个对应一类业务场景）
- 工具层：API + 知识图谱（业务流程 / FAQ）+ 向量库（开放问答）
- 数据层：对话 trace → 结构化 BI（可选 Compass / 分析 pipeline）

关键工程决策：
1. 配置与实现分离：业务专家通过 Prompt Hub + JSON 配置自助上线新场景
2. Eval flywheel：simulation rubric 上线前 + production trace 反哺 + LLM judge 与人类 reviewer 校准
3. 知识图谱存业务流程：可更新、可审计、可被多 Agent 复用
4. Trace-driven 重构：每周抽 trace 看，找到重复/低效步骤立刻重构
5. 对话作为数据产品：ontology pipeline 把对话转结构化业务信号

成果（量化）：
- Resolution rate：[A]% 一次性解决
- Correctness：[B]%
- Out-of-scope：[X]% → [Y]%
- Cost per conversation：[P] → [Q]
```

**面试常被问到的延伸问题**：
- "Supervisor 路由错了怎么办？" → **支持 subagent 中途把控制权交回 supervisor**（Lyft 的 meta-agent 设计）
- "怎么评估 Agent？" → **rubric 要 narrow + behavior-specific**，不要通用指标；LLM judge 要和人类 reviewer 校准
- "Prompt 改了怎么知道没退化？" → eval set 当 regression test，每次 prompt 改动都跑同一组 scenario
- "怎么发现新需求？" → 看 trace 的 out-of-scope / failure cluster，**不是看 dashboard 数字**
- "Agent 改了业务流程怎么办？" → **Neo4j 知识图谱 + CI/CD**，业务专家直接更新 ontology，pipeline 几小时生效

---

## 配套阅读

- **同主题同思想**：[Klarna](blog/posts/2026-09-15-klarna-customer-support-multi-agent.md) — 早期 CX Agent 的奠基案例（70% 自动化）
- **架构演进对比**：[monday Sidekick](blog/posts/2026-09-15-agent-sidekick-bounded-responsibilities.md) — 单 Agent → 多层架构的另一案例
- **Governance**：[Governed Agents](blog/posts/2026-09-15-governed-agents-cost-control-compliance.md) — 怎么给 Agent 加 cost / compliance 控制

参考资料：

- [CX Agents in Production](https://www.langchain.com/blog/customer-experience-cx-agents-in-production-lessons-from-lyft-vodafone-and-latam-airlines) — Jess Ou, LangChain
- [Lyft self-serve platform](https://www.langchain.com/blog/lyft-built-a-self-serve-ai-agent-platform-for-customer-support-with-langgraph-and-langsmith)
- [Vodafone Super TOBi](https://www.langchain.com/blog/customers-vodafone-italy)
- [LATAM Concierge interrupt](https://www.youtube.com/watch?v=RnLCl3ilRgo)
