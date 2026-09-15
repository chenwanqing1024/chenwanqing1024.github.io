---
title: Managed Agents 架构：把"大脑"和"双手"解耦的 5 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, Agent 架构, Harness]
summary: 把 Anthropic Managed Agents 工程文章拆成 5 个架构级模式：Pet vs Cattle 的容器陷阱、脑-手解耦、Sandbox 安全边界、Session ≠ Context Window、Many Brains Many Hands。每个模式给定位 + 推论 + 工程落地的具体做法，可以直接拿去面试讲 Agent 架构。
source-url: https://www.anthropic.com/engineering/managed-agents
source-title: Building Managed Agents
source-author: Lance Martin, Gabe Cemaj, Michael Cohen (Anthropic)
---

## 引子

Anthropic 2026 年初发的 *Building Managed Agents*，讲的不是 Claude 怎么变强，而是**怎么给 Claude 造一个能撑住长时任务的"壳"**。这篇是他们花了 18 个月把内部 agent 基础设施推倒重来的复盘，论点只有一句：**让 Agent 系统像操作系统一样虚拟化——把大脑（Claude + harness）和双手（sandbox / tools）拆开**。

读这一篇，胜过读 10 篇"Agent 入门"。它处理的是真正的工程难题：模型升级时 harness 假设的失效、容器崩溃时 session 的丢没、安全边界的渗透、TTFT 的延迟成本。下面把它拆成 5 个**架构级**模式，按"陷阱 → 解法 → 安全 → 上下文 → 规模化"递进排列。每个模式给定位 + 推论 + 工程落地。

---

## 1. Pet vs Cattle：把 Harness 塞进同一个容器是反模式

**一行定位**：把 session、harness、sandbox 塞进同一个容器 = 把基础设施搞成了"宠物"——一旦生病，整个 session 都陪葬。

**Anthropic 的踩坑**：
- 文件编辑是 syscall，没服务边界——看起来很简洁。
- **但容器一卡，session 就丢**。他们只能从 WebSocket event stream 反推"哪里坏了"，但容器、harness、event stream 三种故障在 stream 里看起来一样。
- 想调试？只能 `docker exec` 进容器——**容器里又有用户数据**。等于是"不能 debug，因为 debug 会泄数据"。

**面试可讲的角度**：*这就是"高内聚"的代价——内聚度越高，故障域越大*。微服务为什么要拆？一个核心理由是隔离故障域。Agent 容器如果把所有组件塞一起，等于把"harness bug"、"网络丢包"、"容器失联"三种故障耦合到一个进程里。

**工程落地**：
- **任何 Agent 基础设施，第一刀先做故障域拆分**：session 存哪、harness 跑哪、sandbox 在哪——这三个必须独立。
- **可观测优先于可调试**：先把"哪种组件坏了"在 metric / log 里能区分出来，再谈性能。
- WebSocket event stream 不是 telemetry——它是**唯一**的 telemetry 来源时，就是在用 channel 当 metric。

---

## 2. 解耦"大脑"和"双手"：Harness 不再住在容器里

**一行定位**：Harness 通过 `execute(name, input) → string` 把 sandbox 当工具调，sandbox 死了就重启——harness 自己也是 cattle。

**Anthropic 的做法**：
- Harness **退出容器**。容器变成 cattle：`provision({resources})` 起新容器，`execute(name, input)` 跑命令。容器挂了，harness 把错误当 tool-call 失败回传 Claude，Claude 决定要不要重试。
- Harness **自己也变成 cattle**。Session log 在外部存着，harness 挂了用 `wake(sessionId)` + `getSession(id)` + `emitEvent(id, event)` 就能从最后一个事件恢复。
- **核心接口只有 3 个**：`execute`、`provision`、`wake` / `getSession` / `emitEvent`。抽象干净到能在不破坏上层的前提下换实现。

**面试可讲的角度**：这是经典的 *dependency inversion*——harness 不依赖具体容器，只依赖"执行 + 持久化"两个抽象。日后想换容器技术（K8s → Modal、Firecracker → gVisor）、换 session 存储（PostgreSQL → S3 + DuckDB），harness 一行代码不用改。

**工程落地**：
- **接口先行，实现后置**。设计 harness 时第一件事是写接口签名：`execute(sandbox_name, command, timeout) -> SandboxResult`、`get_events(session_id, since_seq) -> list[Event]`。实现可以糙，接口必须稳。
- **Harness 进程无状态**——所有状态都从 session log 读。这意味着 harness 可以水平扩，挂了重启零成本。
- **故障注入测试**。定期把 sandbox kill -9、把 harness 进程 kill，验证 session log + wake 协议真能复原。

---

## 3. 安全边界：Token 永远不能从 Sandbox 里被读到

**一行定位**：Claude 生成的代码跑在 sandbox 里，**凭据必须在 sandbox 外**——只通过代理注入，不暴露。

**Anthropic 的踩坑**：
- 第一版 sandbox 和 harness 在一个容器，**Claude 写的代码能直接读环境变量里的 token**。一次 prompt injection = token 全丢 = 攻击者能开新 session 自由发挥。
- "限制 token 权限"是 obvious mitigation，但这又编码了一个"Claude 不够聪明"的假设——模型在变强，假设会过期。

**Anthropic 的两套模式**：
- **把 token 绑到资源上**：Git 的 access token 在 sandbox 初始化时 clone 仓库绑到 local git remote，git push/pull 自动用 token，**Agent 本身从不接触 token**。
- **Vault + 代理**：MCP 工具的 OAuth token 存在外部 vault；Claude 调 MCP 工具时，专用代理从 vault 取 token 转发到外部服务，**harness 完全不知道 token 存在**。

**面试可讲的角度**：这是 *zero trust* 在 agent 系统的落地——不要假设 sandbox 是可信边界，"任何在 sandbox 里能读到的都假定被攻击者拿到"。具体做法是把凭据绑到操作（"用这个 token clone 这个仓库"），而不是放到环境里（"环境里有 token"）。

**工程落地**：
- **MCP server 跑在 sandbox 外**。Agent 进程只能通过 MCP client 调，token 在 server 端。
- **Git token 走 SSH/HTTPS credential helper**，不放在环境变量里。
- **凭证生命周期 = 资源生命周期**：和某个 session / 仓库绑定的 token，session 结束自动吊销。
- **Prompt injection 红队测试**——定期用 PoC 注入诱导 Agent 调 `cat $GITHUB_TOKEN`，验证确实读不到。

---

## 4. Session ≠ Context Window：上下文是可恢复的对象

**一行定位**：Session 是 **durable event log**，context window 是 **当前回合喂给模型的窗口**——前者远大于后者，且不可逆丢失。

**Anthropic 的论点**：
- 长任务必然超过 context window。常规做法（compaction、memory tool、context trimming）**全是不可逆决策**——决定哪些 token 丢掉，但**未来几轮需要的 token 往往正是被丢的那些**。
- **正确做法是把 session 当成"上下文对象"**，存在 Claude 的 context window 之外。Harness 通过 `getEvents()` 接口按位置切片读取（从上次位置继续、倒回几轮看上下文、在某个 action 前回看）。
- Harness 决定**怎么把 slice 喂给 context window**——可能压缩、可能 cache 友好化、可能 summary。这是 harness 的事，不算 session 的事。
- **关注点分离**：session 只保证 durable + 可切片读取；context engineering 留给 harness，未来模型怎么变都不影响 session。

**面试可讲的角度**：这是 *event sourcing* 模式应用到 LLM——把对话当作事件流而不是状态快照。好处是任何时刻可以"穿越"到某个事件点：回放、重做、找某个决策的上下文。坏处是存储成本——但存储比"忘了一个关键约束导致任务失败"的代价低多了。

**工程落地**：
- **Event log schema 必须稳定**：`{seq: int, ts: datetime, type: enum, payload: dict}`。改 schema 等于丢失全部历史。
- **Context 装载策略放 harness，不放 session**。比如 prompt cache 命中率优化、context 重组、token 预算分配——都是 harness 的职责。
- **Compaction 必须可逆**：压缩前先 snapshot，事后能从 snapshot + 后续 events 重建。Anthropic 的 compaction 就是"丢弃已压缩 messages"——必须保证压缩前的 messages 在 session log 里还在。

---

## 5. Many Brains, Many Hands：TTFT 砍 90% 的延迟账

**一行定位**：把 harness 从容器里拆出来之后，**session 不再付容器启动成本**——harness 无状态、按需起 sandbox。

**Anthropic 的数据**：
- 老架构：每个 session 一个容器，harness 在容器里。**容器没起来，模型推理就不能开始**。每个 session 都要 clone repo、起进程、拉 pending events——死时间全算进 TTFT。
- 新架构：harness 无状态，从 session log 拉 pending events 后**立即开始推理**。需要 sandbox 的时候才 `provision()`。
- **p50 TTFT 降 60%，p95 降 90%**。用户感受最强的延迟砍掉一个数量级。

**面试可讲的角度**：这就是 *lazy initialization* 在分布式系统里的经典案例——把昂贵的初始化（容器、repo clone、依赖安装）从"必须前置"改成"按需触发"。**不是所有 session 都需要 sandbox**（纯研究、问答、规划），但老架构每个 session 都得付这个钱。

**工程落地**：
- **Harness 进程池预热**。Sandbox 池子保持 warm pool，provision 时间从 30s 降到 200ms。
- **Sandbox 类型按需选择**。研究型 Agent 不需要完整容器，一个 Python REPL 就够了；代码执行才需要完整 container。**接口统一，但 backend 分级**。
- **Brain-to-hand 通信走 message queue**，不直接 RPC——这样 brain 挂了不影响 hand 在跑的任务，hand 挂了 brain 重启即可。

---

## 一句话总结

Managed Agents 这篇真正的工程遗产是**一个架构判断**：模型会持续变强，所以**对模型行为的假设要可废弃**（context anxiety 案例）；但**对组件边界的抽象要长存**（session / harness / sandbox 三层接口）。前者是产品决策，后者是工程决策——后者决定了你能多快跟上前者。

## 配套阅读

- **同主题**：claude-agent-sdk-engineering — SDK 怎么把 harness 抽象落到代码
- **执行机制**：tool-use-engineering-patterns — `execute` 接口在 tool 层的对应
- **评测视角**：eval-and-observability-patterns — event log 是 observability 的天然数据源

参考资料：

- [Building Managed Agents](https://www.anthropic.com/engineering/managed-agents) — Lance Martin / Gabe Cemaj / Michael Cohen, Anthropic
- [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)