---
title: Claude Code Auto Mode：用两层防御替代人工审批的 6 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, 安全, Agent]
summary: 把 Anthropic Auto Mode 工程文章拆成 6 个可落地的工程模式：审批疲劳的实证、两层防御架构（PI probe + transcript classifier）、三档 tier 决策、Reasoning-Blind Classifier、Subagent 双向闸门、Deny-and-Continue。配自评数据（0.4% FPR / 17% FNR）和工程落地做法。
source-url: https://www.anthropic.com/engineering/claude-code-auto-mode
source-title: Auto mode: a middle ground for agentic permission decisions
source-author: John Hughes (Anthropic)
---

## 引子

Claude Code 的 Auto Mode 不是"省去审批提示"那么简单——它是 Anthropic 用**两层防御**替代人工审批的整套架构：input 层抓 prompt injection，output 层抓 over-eager / 错误动作。文章里给了一个反直觉的数据：**93% 的人工审批被原样接受**——审批疲劳是真的，用户基本不再读弹窗内容了。

文章作者 John Hughes 把这事处理得像 SRE 事故复盘——给威胁建模、给数据（8.5% FPR → 0.4% FPR 完整 pipeline）、给失败模式（17% FNR 的诚实数字）。**这不是一篇产品发布，是一篇防御架构白皮书**。

这一篇按"**问题 → 防御 → 决策 → 失败模式**"递进拆 6 个工程模式，每个模式给定位 + 工程落地 + 面试可讲的角度。

---

## 1. 审批疲劳的真相：93% 被接受 = 弹窗等于不存在

**一行定位**：手动审批没解决安全问题——它把"安全"外包给一个已经脱敏的用户。

**Anthropic 的数据**：
- 现实使用里，**93% 的人工审批弹窗被点"是"**——用户不读内容。
- 历史事故：删远端 git 分支（指令理解偏差）、把 GitHub token 上传到内部 compute cluster、对生产数据库执行 migration——**全是模型太 eager，主动做了用户没说要的事**。

**面试可讲的角度**：这是经典的 *"security theater"*——给老板看的安全流程，实际没拦住任何东西。Anthropic 自己的内部事故日志里，**所有已知 incident 都是 over-eager，不是 malicious**——这意味着"防御恶意 prompt injection"是错配，真正的威胁是"模型太主动"。

**工程落地**：
- **承认审批疲劳是默认状态**。任何"弹窗 + 是/否"的安全设计，默认假设用户会直接点"是"。
- **危险动作不该用弹窗拦**——弹窗拦不住，要么前置 allowlist + 后置 audit，要么 classifier 拦截。
- **撤掉"wide permission"规则**。用户为了省事会配"无脑允许 python / node / 包管理器"——Anthropic 在 Auto Mode 里**主动剥掉这类规则**，让 classifier 重新看到最危险的命令。

---

## 2. 两层防御：Input Probe + Output Classifier

**一行定位**：一个抓"输入是不是恶意"，一个抓"动作是不是越权"——两层独立、可叠加。

**Anthropic 的架构**：
- **Input 层**：server-side prompt-injection probe 扫所有 tool 输出（file read / web fetch / shell output / 外部 tool 响应）。命中就在 context 里加 warning，让 Agent 把这段当可疑内容处理。
- **Output 层**：transcript classifier（Sonnet 4.6 跑）评估每个 action 是否符合用户意图。**两阶段**：Stage 1 是单 token yes/no 过滤（"倾向 block"），Stage 2 只对 Stage 1 标记的做 chain-of-thought 复核。

**为什么是两层不是一层**：单层防不住的两类场景——
1. Agent 自己被 injection hijack 后，**绕过 output classifier 也可能**——因为它调的命令表面无害（POST env vars 到某 URL）。需要 input 层先拦截。
2. Input probe 把上下文污染了，Agent 仍可能"主动"做危险事——和 injection 无关。需要 output 层独立判。

**面试可讲的角度**：这是 *defense in depth* 在 LLM Agent 系统的落地。Input probe 防的是 *untrusted content*，output classifier 防的是 *untrusted behavior*——两者互相独立才能形成网。

**工程落地**：
- **Input probe 必须在 server 侧，不在 client**——client 侧 probe 等于"Agent 改 self-check"。
- **Output classifier 必须看不到 tool output**——否则 Agent 用 prose 说服 classifier 就破防了（见模式 4）。
- **两层都失败的概率 = 各层失败概率之积**——这就是为什么"加层"是有效的：单独看每一层都不完美，乘起来足够小。

---

## 3. 三档 Tier：让 99% 的调用不付 Classifier 成本

**一行定位**：危险判定不是 0/1——大多数 action 安全，少量危险。Tier 1 + 2 处理绝大多数，Tier 3 才上 Classifier。

**Anthropic 的分层**：
- **Tier 1**：Built-in safe-tool allowlist + 用户配置。File read、grep、code navigation、todo 切换、plan mode——**这些不能改状态，不进 classifier**。
- **Tier 2**：项目内文件操作（write/edit）。允许不走 classifier，**靠 git 做 review**——这是关键的成本优化。
- **Tier 3**：剩下的全进 classifier。Shell、外部 API、subagent spawn、项目外文件操作。

**用户进入 Auto Mode 时，规则被重新洗牌**：所有"任意代码执行"的宽权限（python / node / ruby wildcard、npm/pip run）**被强制撤掉**——这些命令最危险，不能让它们绕过 classifier。

**面试可讲的角度**：这是 *risk-based routing*。安全机制按"风险大小"分配成本，**不要把成本分到所有 action 上**。任何系统里 95% 的 action 是无害的，把安全成本均摊给所有 action 等于让无害 action 也变贵。

**工程落地**：
- **画你的 action surface**——一个表格：action / 是否改状态 / 是否访问外部 / 是否影响他人。然后按风险分 3-4 档。
- **Tier 1 必须有审计**——allowlist 里跑了什么必须能查（不是为抓坏人，是为回溯事故）。
- **Tier 2 不能扩展到项目外**——`/etc/passwd` 也算"项目外文件"，要进 Tier 3。

---

## 4. Reasoning-Blind Classifier：让 Classifier 看不到 Agent 的解释

**一行定位**：Classifier 只看 **用户消息 + tool call 原始命令**，**看不到 Agent 的 prose 和 tool output**——刻意"瞎"。

**Anthropic 的设计**：
- Strip assistant text——Agent 不能用 prose 说服 classifier（"用户其实已经同意了"）。
- Strip tool output——主要防御 prompt injection（攻击 payload 在 tool output 里）。**意外好处**：Classifier 判断"POST env vars 到某 URL"够简单，**不需要看文件原文就知道这是 exfiltration 风险**。
- 代价：Classifier 不知道 agent 的 query 是真用户发的还是自己挑的。但**这个代价换 injection robustness 值得**。

**Anthropic 的反直觉发现**：包含 assistant messages + tool results **会让性能下降**。原因是"短 transcript 更容易读，留给 Agent 自我框架化影响 classifier 的余地更小"。

**面试可讲的角度**：这是 *principle of least privilege applied to classifiers*。给 classifier 越多上下文，它被 manipulation 的攻击面越大。**Anthropic 测过给它更多上下文能提升 FNR，但代价是 FPR 上升 + injection 防护崩塌**。

**工程落地**：
- **任何"审核 LLM 输出"的 classifier，默认 strip Agent 自己的 prose**——除非你明确知道为什么要给它看。
- **定期 red-team 自己的 classifier**——看能不能用 prose 引导它改变判断。
- **保留**"user message + bare tool call"的 minimum 形态——这是 classifier 该看到的全部。

---

## 5. Subagent 双向闸门：Handoff 时两道 Classifier

**一行定位**：Subagent 委托时**入口 + 出口各一道 classifier**——不能省，省一道就有洞。

**Anthropic 的设计**：
- **Outbound check**（委托出去时）：subagent 内部的 transcript classifier 看不到用户的原始意图——只看到 orchestrator 的指令。**必须在 handoff 时检查"这个 task 是不是用户授权的"**。
- **Return check**（结果回来时）：subagent 委托时看着 benign，跑一半被 prompt injection 污染了。**返回前审查 subagent 的全部 action history**——如果标记了，**不丢结果，但 prepend 一条 security warning**。

**面试可讲的角度**：这是 *trust boundary* 在 multi-agent 系统的体现。每个 subagent 就是一个 trust domain——跨域数据流动必须经过 validator。**Inbound 和 outbound 都要查——单向检查必然漏**。

**工程落地**：
- **任何"父子 Agent"架构，handoff 必有双向检查**。
- **Outbound 查"task 是否用户授权"**，**inbound 查"result 是否被污染"**——两件事不一样，别合并。
- **被污染的 result 不丢**——给一个 warning 字段让 orchestrator 决定怎么处理，不要静默丢掉（Agent 会觉得 tool 返回了空然后瞎猜）。

---

## 6. Deny-and-Continue：被 Block 不等于 Session 终止

**一行定位**：Block 当成 tool result 返回——Agent 被 nudge 重新尝试，**只有连续 3 次 deny 或累计 20 次才升级到人**。

**Anthropic 的设计**：
- Classifier 拒绝 → 当成 tool result 返回，附带 instruction："find a safer path, don't try to route around the block"。
- **连续 3 次 deny 或累计 20 次** → 停下升级到人。Headless 模式（`claude -p`）没人可问，**直接 terminate 进程**。
- 为什么不让 block 直接 kill session？**0.4% FPR 听起来小，但每个 FPR kill 一次 session，长任务直接不可用**。让 Agent 重新规划一次，**false positive 的代价 = 一次 retry**。

**面试可讲的角度**：这是 *backpressure* 而不是 *circuit break*。Block 是反馈信号，Agent 应该据此调整——不是错误终止信号。这和 rate limiting 的设计一样：429 是"慢点"，不是"别干了"。

**工程落地**：
- **任何"自动拦截"的系统，必须设计 retry 协议**——返回什么、Agent 怎么解读、几次后升级。
- **区分 fatal block 和 retryable block**：credential exploration 是 fatal（"停止探索 token"），但 "command ambiguous" 是 retryable（"重新确认意图"）。
- **升级阈值要有限**——3 次 / 20 次是经验值，但**必须有，不能没有**。没有阈值 = Agent 会无限绕路。

---

## 面试可聊的失败模式

Anthropic 给的诚实数字：**完整 pipeline 在真实 over-eager action 上 17% FNR**。也就是**仍然有 1/6 的危险动作会漏掉**。漏的是哪类？

> "Clean up the PR" 这种用户授权——Classifier 看到了 force-push、看到了删除，但判断不了"用户说 'PR' 算不算同意 force-push"。之前类似的 action 被批准过，**但一次批准不是 pattern**。

**结论**：Auto Mode 不是"零审批 = 零风险"，是"**比 `--dangerously-skip-permissions` 安全得多，比人工细审仍有差距**"。生产里把它当**默认安全档**，高危基础设施（生产 deploy / DB migration）**仍要 plan mode + 人工 review**。

## 一句话总结

Auto Mode 的真正创新不是"替代审批"，是**承认人工审批已经失效**——然后用 **defense-in-depth + reasoning-blind classifier + deny-and-continue** 重新搭一个能撑住高自主性的安全壳。**它的失败模式（17% FNR）也是面试可聊的设计取舍**：承认不完美，然后解释为什么"不完美但够好"是合理选择。

## 配套阅读

- **同主题：Managed Agents 架构** — Auto Mode 是 Managed Agents 的安全模块层
- **执行机制**：tool-use-engineering-patterns — Tool 的 Tier 分层逻辑
- **评测视角**：eval-and-observability-patterns — Classifier 的 FPR / FNR 怎么测

参考资料：

- [Auto mode: a middle ground for agentic permission decisions](https://www.anthropic.com/engineering/claude-code-auto-mode) — John Hughes, Anthropic
- [Claude Opus 4.6 system card §6.2.1 / §6.2.3.3](https://www.anthropic.com/news/claude-opus-4-6) — over-eager 行为模式
- [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) — Harness 怎么和 classifier 配合