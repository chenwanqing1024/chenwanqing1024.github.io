---
title: Governed Agents 框架：把 LLM Gateway 当成 Agent 的 runtime control plane——5 层治理 + 简历级骨架
date: 2026-09-15
tags: [Agent, LLM Gateway, 治理, 成本控制, 合规, 工程实践]
summary: 把 LLM Gateway 定位为 Agent 的 runtime control plane（不是简单的 model router）。5 个治理动作：identity / spend / model routing / context efficiency / guardrails。Govern / Decide / Protect / Observe / Assure 5 步运转框架。附完整简历项目骨架。
source-url: https://www.langchain.com/blog/building-governed-agents-a-framework-for-cost-control-and-compliance
source-title: Building Governed Agents: A Framework for Cost, Control, and Compliance
source-author: Martha Janicki (LangChain)
---

## 引子

Agent 进入生产后，**3 个新压力出现**：token 花销失控、uptime / continuity 要求、隐私 / 安全 / AI 监管要求。**LLM Gateway 不是简单的 model router**——它是 Agent 的 **runtime control plane**，把 policy 翻译成每次 model call / tool call / agent hop 上的可执行决策。

面试讲 Agent 治理 / 成本控制 / 合规设计，这 5 层架构 + 5 步运转框架直接搬。

---

## 核心思想：Governance = 把政策落到每次调用上

**Governance vs Gateway**：

- **Governance** = 规则（identity、ownership、risk tier、policy）
- **Gateway** = 强制执行（authenticate、route、redact、spend cap、retry）

> "An LLM gateway is the **runtime control plane** for those decisions. It gives enterprises a single place to: Authenticate usage / Select approved models / Minimize exposed context / Enforce data and spending policies / Manage failures / Retain evidence as to what decisions were made."

**关键判断**：**Gateway 是 infra 不是 feature**——它要和 tracing / evaluation / monitoring 联动，否则它就是个 black box。

---

## 5 步运转框架

```
[Govern]  ── Establish identity, ownership, risk tiers, policy
     ↓
[Decide]  ── Select models, escalate requests, fail over when needed
     ↓
[Protect] ── Enforce controls at each call boundary
     ↓
[Observe] ── Measure behavior outcomes
     ↓
[Assure]  ── Preserve decision lineage, manage change over time
```

**3 个常见起点**（不同组织的优先压力不同）：

| 起点 | 优先压力 | 第一步 |
|---|---|---|
| **Visibility-led** | AI-native 组织，token 烧太快 | 先 Observe（trace + token breakdown） |
| **Control-led** | 敏感数据组织（金融 / 医疗 / 政府） | 先 Protect（redaction + provider routing + residency） |
| **Assurance-led** | 强监管组织 | 先 Assure（policy versioning + audit logs + eval history） |

**所有成熟组织最终都需要 3 个都做**——但起点可以不同。

**面试可讲角度**：这是 *risk-driven prioritization* 的工程化。**不同组织的合规 / 业务压力不同，治理不是"全做"——是从最痛的点切入**。

---

## Gateway 的基础：先治理"环境"才能治理"流量"

**关键警告**：

> "If the underlying platform is not secure, no amount of routing or policy logic above it can compensate."

**7 个基础能力**（缺一不可）：

1. **Security** — 加密（at rest / in transit）、shared-responsibility model、第三方安全验证
2. **Authentication / Identity** — SSO（SAML / OIDC）+ JIT provisioning + 接到企业 IdP（不是单独 login）
3. **Audit logs** — 不只记"谁跑了什么"，还要记"policy version / outcome / tools / providers"
4. **User management** — RBAC + SCIM 自动 provisioning
5. **Provider secrets** — **集中存**（不要每 Agent 写死 API key），rotation 一次完成
6. **Data separation** — team / workspace 隔离，不能所有用户看所有 trace
7. **Data residency** — 监管要求的地域 / 基础设施隔离

**面试可讲角度**：这是 *defense in depth*。**Gateway 上层的 policy enforcement 依赖底层的基础设施安全**——任何一层漏了，整条链路就破。

---

## 4 类交互、4 类风险

Agent 不只调 LLM——还调 tool / MCP / A2A。**每类交互有不同风险**：

| 交互 | 风险 | 治理要求 |
|---|---|---|
| **LLM call** | 成本、模型可用性、私密数据进 provider logs | spend limits、redaction、provider routing |
| **Tool call** | 误操作生产系统 | 权限、audit trail |
| **MCP call** | 数据出基础设施边界 | 访问控制、logging |
| **A2A call** | agent chain 复合错误 / 越权 | 每 hop tracing、policy enforcement |

**关键判断**：

> "For agents, **the greatest risk is often not what the model says, but what the agent can do.**"

**模型输出过滤**只是一部分。**真正的治理是"agent 能做什么"——哪些 tool、哪些 credentials、哪些动作需要 human approval**。

**面试可讲角度**：这是 *action governance* vs *content governance*。**大多数团队只做了 content filtering（prompt injection / PII / jailbreak），没做 action governance（哪些 tool / 哪些写操作 / 哪些凭证）**。**Action governance 才是 Agent 治理的核心**。

---

## 5 个核心治理动作（可直接落地）

### 1. Spend controls — 不是财务工具，是事故信号

**Spend 政策结构**：

```
[Organization] → [Business Unit] → [Team] → [API Key] → [User]
       ↓              ↓             ↓          ↓         ↓
     月 cap         周 cap        日 cap     每 agent  单用户
```

**关键工程**：
- **每 agent / 每 workload 一个 API key**——这样不用专门追踪系统就能 cap
- **Daily + weekly + monthly 多层 cap**——避免月 cap 太宽导致月末才发现失控
- **Default policies**——避免每个 team 单独配置
- **Sudden spend spike = agent 异常信号**——比 alert 更早发现问题

**面试可讲角度**：**Spend policy 不是财务问题，是 observability 工具**。**Spend 异常通常是 agent bug 的第一个信号**——比 latency / error rate 更灵敏。

### 2. Model routing — 不是"便宜任务用便宜模型"那么简单

**真模型路由**：

```
[Task profile: difficulty / latency budget / cost budget / risk tier]
       ↓
[Routing policy]
       ↓
[Model selection]  ← 不是"hardcoded 哪个模型"，是按 profile 选
```

**关键判断**：

> "Most people think of model routing as a way to send easy prompts to cheaper models, but **it also matches each task with a model that is approved for that use case and meets the required standards for quality, latency, cost, and risk.**"

**路由 = 投资组合管理**：把对的 model 用在对的任务上。**不是"省钱"是"风险管理 + 性能优化 + 成本优化"的三角平衡**。

### 3. Context efficiency — token 用在哪就省在哪

**Context 决定 token**——token 决定 cost + latency。

**治理思路**：
- **Tracing 找 context growth**——哪些调用在送大 context
- **Evals 决定能删多少 context**——删了不影响质量
- **Monitoring 检测 quality regression**——删过头了立即报警

### 4. Failover — 不是 fallback 到"任意可用 model"

**Fallback 的硬规则**：

> "**A backup model is considered valid only when it is policy-equivalent**, meaning it satisfies the same requirements for data handling, residency, and safety."

**不是 fallback 到 OpenAI 是 Anthropic**——是 fallback 到**满足同样合规 + 数据 + 安全的** model。

**Fail-open vs Fail-closed**：
- **Fail-open**：gateway 挂了，请求直接过（适合低风险 internal tool）
- **Fail-closed**：gateway 挂了，请求拒绝（适合高风险 external customer-facing）

**按 workload risk 选**——不要全 gateway 一种行为。

### 5. Guardrails — pattern-based + model-based 双轨

**两类 guardrail**：

| 类型 | 检测方式 | 适用 |
|---|---|---|
| **Pattern-based** | regex / rules | SSN、信用卡、email、API key |
| **Model-based** | NER / LLM judge | 姓名、地点、政治倾向、prompt injection |

**关键警告**：

> "Guardrails reduce risk, but they do not eliminate it. **Pattern-based controls may miss unfamiliar formats, while model-based detection is probabilistic and can produce both false positives and false negatives.**"

**Guardrail 必须配合其他防护**：
- **Consequential actions 走 deterministic limits 或 human approval**——不能只靠 content detection
- Guardrail 是**第一道防线**，不是唯一防线

**面试可讲角度**：这是 *defense in depth for LLM*。**任何 content filter 都不能 100% 准确**——必须配合 action gating（审批、确定性规则）、data minimization（敏感数据别进 context）、human-in-the-loop（高风险动作必须人工）。

---

## Compliance 适配：5 个主流监管框架

| 监管 | 适用 | 关键要求 |
|---|---|---|
| **CCPA** | 加州消费者 | 知情权、删除权、opt-out |
| **GDPR** | 欧盟 | 合法基础、访问 / 更正 / 删除权 |
| **EU AI Act** | 欧盟 AI 系统 | 按 risk 分级 + 透明度 + human oversight |
| **HIPAA** | 美国医疗 | PHI 保护 + BAA 协议 |
| 各行业细分 | 金融 / 教育 / 政府 | 行业特定 |

**工程建议**：**不是"做哪个就做完所有"**——按业务实际接触的合规要求精准施加 controls，**每多一个要求 = 多成本 + 多 latency + 多复杂度**。

---

## 简历可直接借用的项目骨架（LLM Gateway / Agent 治理类）

```
项目名：[公司名] LLM Gateway / Agent Runtime Control Plane

角色：核心工程师 / Platform Lead

5 步运转框架：
1. Govern — Identity / RBAC / Risk Tier / Policy
2. Decide — Model routing + Escalation + Failover
3. Protect — Per-call controls (redaction / permission / spending)
4. Observe — Tracing + Token breakdown + Behavior metrics
5. Assure — Policy versioning + Audit logs + Eval history

7 个基础能力：
Security / AuthN (SSO+SCIM) / Audit logs / User mgmt / Provider secrets / Data separation / Residency

4 类交互治理：
- LLM call → spend cap + redaction
- Tool call → permission + audit
- MCP call → access control + logging
- A2A call → per-hop tracing + policy

5 个核心治理动作：
1. Spend controls（multi-tier cap + API key per workload）
2. Model routing（按 profile 选 model，不是 hardcoded）
3. Context efficiency（trace → eval → monitoring 闭环）
4. Failover（policy-equivalent fallback + fail-open/closed by risk）
5. Guardrails（pattern + model 双轨，配合 action gating）

合规适配：[GDPR / EU AI Act / HIPAA / CCPA]

成果（量化）：
- Token cost：[A]% 下降
- Spend spike detection 时间：[N] 小时 → [M] 分钟
- Audit trail 完整性：[B]% 决策可追溯
- Provider failover：[X] ms 内完成
- 合规审计通过率：[Y]%
```

**面试常被问到的延伸问题**：
- "Gateway 和直接调 provider API 有什么区别？" → **Gateway 是 runtime control plane**——authenticate / route / redact / cap / retry / audit 一次完成，**provider 直连没有这些**
- "Model routing 怎么做？" → **按 task profile（difficulty / latency / cost / risk）路由**——不是 hardcoded 哪个模型，是 policy 驱动
- "Fallback model 怎么选？" → **policy-equivalent**——满足同样合规 + 数据 + 安全要求的 model，**不是任意可用**
- "Guardrail 怎么做？" → **pattern + model 双轨**，但不能 100% 准确，必须配合 action gating + data minimization + human-in-the-loop
- "Spend 异常怎么发现？" → **multi-tier cap + alert**——sudden spend spike 通常是 agent bug 的第一个信号

---

## 配套阅读

- **同主题执行**：[Claude Agent SDK](blog/posts/2026-09-15-claude-agent-sdk-engineering.md) — SDK 层的 budget cap / hook / permission 怎么对应 gateway 概念
- **客户落地**：[Klarna / Vodafone / Lyft](blog/posts/2026-09-15-cx-agents-five-patterns-production.md) — 大规模生产 Agent 怎么用 gateway 控成本
- **Tool design for control**：[Building Tools for Agents](blog/posts/2026-09-15-writing-tools-for-agents.md) — tool 描述怎么写才能让 Agent 在 gateway 后端被有效路由

参考资料：

- [Building Governed Agents](https://www.langchain.com/blog/building-governed-agents-a-framework-for-cost-control-and-compliance) — Martha Janicki, LangChain
- [LangSmith LLM Gateway](https://www.langchain.com/langsmith/llm-gateway)
- [The Agent Development Lifecycle](https://www.langchain.com/blog/the-agent-development-lifecycle)
