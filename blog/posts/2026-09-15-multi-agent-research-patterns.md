---
title: Multi-Agent Research System 实操：Lead + Subagent 架构的 5 个工程教训
date: 2026-09-15
tags: [Claude, AI 工程, Agent, Multi-Agent]
summary: 把 Anthropic 多 Agent Research 系统工程文章拆成 5 个工程教训：多 agent 适用边界（research 强、coding 弱）、LeadResearcher + Subagent + CitationAgent 三段架构、Orchestrator delegation 7 条 prompt 原则、Eval 三件套（小样本 + LLM-as-judge + 人类）、Production 三大工程挑战（stateful / debug / 同步 vs 异步）。配具体数据（90.2% / 15x token / 90% time / 40%）+ 落地边界。
source-url: https://www.anthropic.com/engineering/multi-agent-research-system
source-title: Building a multi-agent research system
source-author: Jeremy Hadfield, Barry Zhang, Kenneth Lien, Florian Scholz, Jeremy Fox, Daniel Ford (Anthropic)
---

## 引子

当 Claude Research 公开时，Anthropic 罕见地写了完整的 production 工程复盘——**Lead agent + parallel subagents + CitationAgent 三段架构**——**multi-agent 比 single-agent 在 research eval 上提升 90.2%**，**但 token 消耗是 chat 的 15×**。这是 2025 年最具工程价值的 multi-agent 实战记录——**它不是讲"多 agent 是什么"，是讲"多 agent 在生产里怎么 work / 怎么 fail"**。理解 Lead + Subagent 的边界比学 prompt 更重要——**因为大多数 multi-agent 失败不是 prompt 错，是架构错**。

下面拆 5 个工程教训，按"**适用边界 → 架构 → prompt → eval → production**"递进。

---

## 1. 适用边界：Multi-agent 适合 breadth-first research，不适合大多数 coding

**一行定位**：**Multi-agent 不是 universal upgrade**——**只有"路径不可预测 + 可并行 + 价值高"的 task 才用 multi-agent**。

**Anthropic 的核心数据**：
- **Multi-agent 比 single-agent Opus 4 在 internal research eval 上提升 90.2%**。
- **Multi-agent 用 15× chat 的 token**。
- **Single-agent 比 multi-agent 慢 + 漏信息**——sequential search 找不到全 IT S&P 500 的 board members。
- **Token usage 解释 BrowseComp 80% 的 variance**——其他 15% 来自 tool call 数 + model choice。
- **Sonnet 4 升级带来的性能提升 > Sonnet 3.7 token 翻倍**——**模型升级比 token 升级更有效**。

**Multi-agent 适合的场景**（Anthropic 自己说的）：
- ✅ **Breadth-first query**——多个独立方向同时探索。
- ✅ **超过单 context window 的信息**——需要 compression。
- ✅ **大量复杂 tools**——每个 subagent 持有不同 tool set。

**Multi-agent 不适合的场景**：
- ❌ **Most coding tasks**——sequential 依赖多 + 真正可并行的少。
- ❌ **强 context 共享**——agents 之间需要同步状态。
- ❌ **价值低 + token 高**——ROI 不划算。

**面试可讲的角度**：这是 *collective intelligence* 的工程应用——**Anthropic 直接类比人类社会**："100,000 年来 single human 没变聪明，但人类社会因为 collective intelligence + coordination 指数级变强"。**Multi-agent 是 LLM 时代的"组织工程"**。**前提是 collective 增益 > coordination cost**。

**工程落地**：
- ☐ **判断 task 是否"路径不可预测"**——可预测就别上 multi-agent
- ☐ **判断 ROI**——multi-agent 15x token，**task 价值够高才上**
- ☐ **大多数 coding 用 single-agent + tools**——multi-agent 在 coding 收益小
- ☐ **优先升级 model 而不是加 agents**——Sonnet 4 > Sonnet 3.7 + 2x token

---

## 2. 三段架构：LeadResearcher + Subagent + CitationAgent

**一行定位**：**Research system = Lead agent 规划 + 多个 subagent 并行 search + CitationAgent 整理引用**——**三段各有职责、context 隔离**。

```
User Query
   ↓
[LeadResearcher]  → 规划 + 派 subagent
   ↓
[Subagent × N]  → 并行 search + 各自 context
   ↓
[LeadResearcher]  → 综合 + 决定是否再 search
   ↓
[CitationAgent]  → 加引用（用 fresh context）
   ↓
Final Report + Citations
```

**Context 边界设计**：
- **LeadResearcher**：200K context——**plan + 综合结果**。**Plan 必须 save 到 Memory**——**超过 200K 会 truncate**。
- **Subagent**：各自干净 context——**只负责自己 aspect**。
- **CitationAgent**：**fresh context**——只看 documents + report + 找引用位置。**不污染 lead 的 context**。

**关键设计**：
- **每个 subagent 持有独立 prompt + tool set**——**separation of concerns**。
- **Subagent 互不通信**——**只通过 lead agent 传话**——**避免 coordination explosion**。
- **CitationAgent 是 post-processing**——**引用问题不影响 lead 的 reasoning**。

**Subagent 任务分配示例**（AI agent companies 2025 调研）：
- Subagent 1：找 AI agent 创业公司 + 融资情况。
- Subagent 2：找 enterprise AI agent vendors + market share。
- Subagent 3：找 AI agent 开源项目 + GitHub stars。
- Lead：综合三份结果 + 加 insights。

**面试可讲的角度**：这是 *master-worker + post-processor* 的 pipeline。**关键设计：每个 agent 有明确职责边界 + context 隔离**。**类比 MapReduce**——map 阶段是 subagents，reduce 阶段是 lead，post-process 是 CitationAgent。

**为什么 Lead 必须 plan + save**：
- **Plan 决定 subagent 怎么拆**——必须 early 决定。
- **Save 到 Memory**——**避免 200K 截断时 plan 丢**。
- **Plan 是 recoverable state**——出错了能从 plan 继续。

**工程落地**：
- ☐ **Lead agent 的 plan 必须持久化**——**Memory / external file**
- ☐ **Subagent 必须 narrow scope**——**别让一个 subagent 干所有事**
- ☐ **Citation / formatting 等 post-processing 放独立 agent**——**fresh context 避免污染**
- ☐ **每个 subagent 跑前明确 output format + boundaries**——**避免重复 work**

---

## 3. Prompt Engineering 7 原则：从原型到生产的迭代经验

**Anthropic 总结的 7 条 prompt 原则**——**早期 agents 失败模式：spawn 50 subagent / 搜不存在 source / 互相 spam**——**这些都靠 prompt 修**。

### 原则 1: Think like your agents（像 agent 一样想）

> **"Effective prompting relies on developing an accurate mental model of the agent."**

**机制**：
- **用 Console 跑 simulation**——**看 agent 每步思考 + 行动**。
- **记录 failure mode**：继续搜到 over-satisfied / 搜 verbose query / 选错 tool。
- **修改 prompt 后看 transcript 验证**——**不要猜 agent 怎么想**。

**面试可讲的角度**：这是 *debugging for LLM agents*——**你不能 step through code，但能 step through transcript**。**Console simulation 是 LLM 时代的 debugger**。

### 原则 2: Teach orchestrator how to delegate（教 orchestrator 委派）

**早期 failure**：lead agent 给 subagent 的 instruction 太简单——"research the semiconductor shortage"——**3 个 subagent 重复搜 2021 chip crisis**。

**正解**：
- **每个 subagent task 配**：objective + output format + tool guidance + boundaries。
- **Lead 必须明确划清 subagent 之间的分工**。

**代码模式**（pseudo-prompt）：
```
Subagent task spec:
- objective: 找 X 公司的 2025 board members
- output_format: list of {name, role, since_year}
- tools: web search only (no Slack/GDrive)
- boundaries: 不要查 customer 反馈、不要查 stock price
```

**工程落地**：
- ☐ **Subagent task 模板**：objective / format / tools / boundaries 4 项
- ☐ **避免短 instruction**——"research X" 必撞车
- ☐ **Lead 必须 explicit 分工**——"subagent 1 查 A，subagent 2 查 B"

### 原则 3: Scale effort to query complexity（按 query 复杂度调 effort）

**早期 failure**：agent 对简单 query 也 spawn 10 个 subagent，**浪费 token + 拖慢**。

**正解**：**在 prompt 里 embed scaling rules**。
- **简单 fact-finding**：1 agent + 3-10 tool calls。
- **直接对比**：2-4 subagents × 10-15 calls each。
- **复杂 research**：10+ subagents，**明确分工**。

**面试可讲的角度**：这是 *resource allocation*——**类比数据库的 query plan**：简单 query 走 index scan，复杂 query 走 full table scan。**LLM agents 也该按 query 调 resources**。

**工程落地**：
- ☐ **Prompt 显式写 scaling rules**——别让 agent 自己决定
- ☐ **Subagent 数量配 query 复杂度**——fact 1 个、对比 3 个、调研 10 个
- ☐ **Tool call 上限**——3-10 / 10-15 / 15+ 按层级

### 原则 4: Tool design and selection are critical（Tool design 关键）

> **"Agent-tool interfaces are as critical as human-computer interfaces."**

**早期 failure**：agent 用 web search 找 Slack-only context——**根本找不到**。

**正解**：
- **Agent 先 enumerate 所有 available tools**——不假设 MCP server 提供的 tool 够好。
- **Tool description 质量参差不齐**——**必须 hard requirement 写好**。
- **Specialized tools > generic tools**——**specific tool 省 context**。
- **Heuristic**："examine all tools first → match to user intent → prefer specialized"。

**工程落地 checklist**：
- ☐ **Tool description 当 prompt 精炼**（见 writing-tools-for-agents）
- ☐ **每个 tool 有 distinct purpose**——不重叠
- ☐ **Prefer specialized tool**——`get_employee` 不如 `get_employee_by_id`
- ☐ **MCP server 装的 tool 必 review**——**别假设描述都写对了**

### 原则 5: Let agents improve themselves（让 agent 改自己）

> **"The Claude 4 models can be excellent prompt engineers."**

**Anthropic 的"tool-testing agent"**：
- 给它一个 flawed MCP tool。
- 它**用 tool 试 + 自己改 description**。
- **跑几十次**——找 key nuances + bugs。
- **结果：未来 agent 用新 description，task completion time 降 40%**。

**面试可讲的角度**：这是 *self-improving agent*——**agent 不只跑 tool，还 review tool description**。**Dogfooding 在 LLM 时代的应用**。**40% time reduction 是巨大 ROI**。

**工程落地**：
- ☐ **建 tool-testing agent**——auto review tool description
- ☐ **让 Claude 改 Claude**——它 systematic review 比人工细
- ☐ **每次 tool description 改完跑 eval**——**40% 改进不是偶然**

### 原则 6: Start wide, then narrow down（先宽后窄）

**早期 failure**：agent 上来就 long specific query——**返回少结果**。

**正解**：**类比专家研究**——先 explore landscape，再 drill into specifics。
- Prompt：**"先用 short broad query 探索 → 评估有什么 → 再 narrow focus"**。
- **类比 human researcher**：先看 review paper，再深读 specific paper。

**工程落地**：
- ☐ **Lead agent 强制先 wide search**——3-5 个 broad query
- ☐ **再 narrow**——基于 wide 结果找 specific angle
- ☐ **避免 premature narrowing**——上来 specific = 漏信息

### 原则 7: Parallel tool calling（并行 tool call）

**Anthropic 的并行两层**：
- **Lead level**：3-5 subagents 并行（不是 sequential）。
- **Subagent level**：3+ tools in parallel。

**结果**：**复杂 query research time 降 90%**——从 hours 到 minutes。

**面试可讲的角度**：这是 *embarrassingly parallel* 的二次应用。**第一层 parallel 是 subagents 之间**，**第二层是 subagent 内 tool call 之间**。**两层都并行 = 90% 提速**。

**工程落地**：
- ☐ **Subagent 必 parallel**——不要 serial spawn
- ☐ **Subagent 内 multiple tool calls 必 parallel**——async / gather
- ☐ **Tool call 之间无依赖就并行**——LLM 决策时显式鼓励

---

## 4. Eval 三件套：小样本 + LLM-as-judge + 人类

**一行定位**：**Multi-agent eval 难点** = **agent path 不可预测**——**不能用"是否按 path 走"评，要评"是否达到结果 + 是否合理过程"**。

### 4.1 小样本起步：20 queries catch 大变化

> **"With effect sizes this large, you can spot changes with just a few test cases."**

**关键 insight**：
- **早期 agent 改动效果大**——30% → 80% success rate 是常见的。
- **20 个真实 query 就够 spot 大变化**——**不需要 hundreds of test cases**。
- **失败模式**："等大 eval 起来再测"——**delay = 慢迭代**。

**工程落地**：
- ☐ **起步 20 个真实 query**——**别追求大 eval**
- ☐ **每次改完跑 20 个**——效果大就一眼看出
- ☐ **Real usage pattern > synthetic**——synthetic 测不出真实 failure

### 4.2 LLM-as-judge：rubric + 0.0-1.0 score

**Anthropic 的 judge design**：
- **单 LLM call + 单 prompt**——**输出 0.0-1.0 score + pass/fail**。
- **Rubric 5 维度**：factual accuracy / citation accuracy / completeness / source quality / tool efficiency。
- **实验多 judge 后选最稳定**——**多 judge 反而 noise 大**。

**Trade-off**：
- ✅ **可 scale**——一次跑 hundreds of outputs。
- ✅ **比人类评一致**——**single prompt 比 multi-prompt 一致**。
- ❌ **LLM judge 有自己的 bias**——必须 human 校准。
- ❌ **对 clear answer 的 case 特别有效**——能 check "top 3 药企 R&D"。

**工程落地**：
- ☐ **Rubric 5-7 维度**——**每个维度独立 score**
- ☐ **Single LLM judge > multi-judge**——**一致性优先**
- ☐ **0.0-1.0 + pass/fail 双 output**——比 binary 详细
- ☐ **Clear answer 的 case 用 LLM judge**——complex case 留 human

### 4.3 Human eval 抓 LLM 漏的

**Anthropic 的发现**：**人类发现 SEO-optimized content farms 比 authoritative PDFs 排名高**——**LLM judge 漏了 source quality bias**。

**关键 insight**：
- **LLM judge 不抓的**：hallucination on unusual query / system failure / subtle source bias。
- **人类抓的**：edge case + 质量判断 + 偏见识别。
- **必须 human eval 补 LLM judge**。

**工程落地**：
- ☐ **定期 human eval**——**每周 / 每次大改后**
- ☐ **让 human 找 LLM 漏的**——**不是确认 LLM 对的**
- ☐ **Human findings 反馈到 prompt**——**source quality heuristics 改 prompt**

---

## 5. Production 三大挑战：Stateful / Debug / 同步异步

**Anthropic 的生产工程经验**——**multi-agent 在生产里遇到的难题和原型完全不同**。

### 5.1 Agents are stateful and errors compound（stateful + 错误复合）

**核心问题**：
- **Agent 跑很久**——**跨多次 tool call 保持 state**。
- **小错 cascade 成大错**——**一步错后面全错**。
- **Restart 从头 = 贵 + 慢 + 用户体验差**。

**Anthropic 的解法**：
- **Resume from failure point**——不重头跑。
- **让 model 处理错误**——告诉 agent tool 失败 → **agent 自主 adapt**。
- **Deterministic safeguard**——retry logic + checkpoints。

**面试可讲的角度**：这是 *error recovery in long-running agents*——**类比 distributed systems**。**Long-running stateful system + partial failure → 必然需要 resume protocol**。**Checkpoint + retry = basic primitives**。

**工程落地**：
- ☐ **每个 agent step 必 checkpoint**——**state 写到 durable storage**
- ☐ **错误时告诉 agent**——**"tool X 失败，try 别的"**
- ☐ **Deterministic retry**——**transient 错 retry / 永久错 escalate**
- ☐ **不要 restart from beginning**——**从 failure point 继续**

### 5.2 Debugging 需要新方法

**核心问题**：
- **Agent 是 non-deterministic**——**同 prompt 跑两次可能不同**。
- **传统 stack trace 没用**——**要看 transcript**。
- **用户报"agent 找不到明显信息"——why？**

**Anthropic 的解法**：
- **Full production tracing**——**每个 agent decision + tool call + reasoning 记录**。
- **High-level observability**——**agent decision pattern + interaction structure**（不监控 conversation 内容，保护隐私）。
- **Diagnose root cause**——**从 trace 反推 failure mode**。

**面试可讲的角度**：这是 *observability for LLM agents*——**类比传统 APM**（Datadog / Honeycomb）——**但 LLM 时代的 observability 还要看 decision pattern**。**不能只看 latency / error rate，要看 "agent 选了什么 tool、为什么"**。

**工程落地**：
- ☐ **Full trace 必上**——**每个 tool call + reasoning 进 storage**
- ☐ **High-level pattern observability**——**不监控内容**（隐私），**监控 decision pattern**
- ☐ **Diagnose workflow**——**failure mode → 找 transcript → 找 root cause → 改 prompt/tool**

### 5.3 Deployment 用 rainbow deployment

**核心问题**：
- **Multi-agent stateful**——**deploy 时 agents 在任何状态**。
- **不能 stop the world 升级**——**会断 running agents**。

**Anthropic 的解法**：
- **Rainbow deployment**——**gradually shift traffic old → new**，**两个版本同时跑**。
- **避免打断 running agents**。

**工程落地**：
- ☐ **Multi-agent 升级必 rainbow**——**别 blue-green 直接切**
- ☐ **运行中 agent 跑老版本**——**新 agent 跑新版本**
- ☐ **观察 failure rate**——稳定了再切 traffic

### 5.4 Sync vs Async execution

**Anthropic 当前的设计**：**Lead agent 同步等所有 subagent 完成再继续**。
- ✅ **简单**——coordination 直接。
- ❌ **Bottleneck**——subagent 串行依赖 lead。

**未来方向**：**Asynchronous execution**。
- ✅ **更并行**——agents 并发 + 动态 spawn 新 agents。
- ❌ **复杂**——result coordination + state consistency + error propagation。

**面试可讲的角度**：这是 *coordination model*——**sync 简单但慢，async 快但难**。**类比 web 框架的 sync vs async request handler**。**Multi-agent 是 LLM 时代的 distributed system**。

**工程落地**：
- ☐ **起步 sync**——**简单 + 够用**
- ☐ **Perf 不够时上 async**——**state consistency 是难点**
- ☐ **每个 async agent 必 idempotent + resumable**——**fail safe**

---

## 5 个工程教训总结

| 教训 | 一句话 | 数据 |
|---|---|---|
| **Multi-agent 不是 universal upgrade** | 只适合 breadth-first + 高价值 task | 90.2% 提升 / 15x token |
| **三段架构** | Lead + Subagent + Citation | Plan 必 save 到 Memory |
| **Prompt 7 原则** | 像 agent 想、教 delegation、scale effort、tool design、self-improve、start wide、parallel | Tool description 优化降 40% 时间 / parallel 降 90% 时间 |
| **Eval 三件套** | 小样本 + LLM-as-judge + human | 20 queries catch big change / single LLM judge > multi |
| **Production 三大挑战** | stateful + debug + sync/async | Rainbow deployment + full trace |

---

## 一句话总结

Multi-agent Research system 的核心教训是**"架构 > prompt > 工具 > 一切"**——**Lead + Subagent + CitationAgent 三段隔离是基础**；**prompt 的 7 原则（delegation / scaling / self-improve / parallel）是 middle layer**；**eval 三件套（小样本 + LLM-as-judge + 人类）是质量保障**；**生产里 stateful + debug + sync/async 是真正的 hard part**。**Multi-agent 不是更好，是更贵——只有在价值高 + 路径不可预测 + 可并行时才用**。**Sonnet 4 升级 > Sonnet 3.7 + 2x token**——**模型升级比 token 升级有效**。

## 配套阅读

- **架构视角**：managed-agents-arch-patterns — Pet vs Cattle + brain-hand decoupling
- **同主题**：building-effective-agents-patterns — workflows vs agents 范式选择
- **同主题**：harness-design-gan-evaluator — Generator-Evaluator loop 在 multi-agent 里的角色

参考资料：

- [Building a multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) — Jeremy Hadfield et al., Anthropic
- [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) — 长期运行的 agent harness
- [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) — workflows vs agents 范式
