---
title: 长时 Agent Harness：Initializer + Coding Agent 双角色模式的 5 个工程实践
date: 2026-09-15
tags: [Claude, AI 工程, Harness, 长任务]
summary: 把 Anthropic Effective Harnesses for Long-Running Agents 文章拆成 5 个工程实践：长时 Agent 的两大失败模式（one-shotting / premature victory）、Initializer + Coding 双角色分工、JSON Feature List 防过度触发、Clean State 协议（git + progress + init.sh）、Puppeteer MCP 闭环自测。配 YAML 示例 + 5 步启动 checklist + 面试可讲的设计取舍。
source-url: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
source-title: Effective harnesses for long-running agents
source-author: Justin Young (Anthropic)
---

## 引子

Claude Agent SDK 是通用 agent harness，理论上 compaction 能让 agent 跑任意久。**实测不行**——给一个"build a clone of claude.ai"的 prompt，Opus 4.5 也会卡在两种 failure mode 上。这篇讲的是 Anthropic 怎么用 **Initializer Agent + Coding Agent** 双角色模式 + 三个文件（`init.sh`、`feature_list.json`、`claude-progress.txt`）让 agent 跨多个 context window 持续推进。

下面拆 5 个工程实践，按"**问题 → 分工 → 状态管理 → 启动协议 → 自测闭环**"递进。每个模式给定位 + 落地代码 / 命令 + 面试可讲的角度。

---

## 1. 长时 Agent 的两大失败模式：One-shotting 和 Premature Victory

**一行定位**：长时 Agent 必栽在两个根上——**贪多嚼不烂**和**看着像完成就交付**。

**Anthropic 的观察**：
- **One-shotting**：agent 想一锤子搞定整个 app → context 在中间耗尽 → 下个 session 接手时**功能半完成 + 无文档** → 猜上下文、debug 老问题，**大量 token 浪费**。
- **Premature victory**：后期 agent 看 git log 有 progress → "看起来做完了" → 实际核心 feature 没测就 declare done。

**即使 compaction 也救不了**——compaction 不总能传清晰指令给下个 session。**新的 session 永远从"零上下文"开始**——想象一个三班倒的工程团队，每班新工程师上班没记忆。

**面试可讲的角度**：这是 *cold-start problem*——分布式系统每个新 worker 都要重新建立 worldview。**长时 agent 是 N 个 cold-start 串起来**，每个都是新 worker。

**工程落地**：
- **承认 compaction 不足以独立支持长任务**——必须有 handoff artifact。
- **One-shotting 的根治**：任务分解到 feature 粒度，**强制一次一个**。
- **Premature victory 的根治**：**outcome 测试**（不是声明 pass，是真的测）。

---

## 2. 双角色分工：Initializer 与 Coding Agent

**一行定位**：**第一次跑的 agent 负责"搭台"**（建 git repo / 写 init.sh / 列 feature list），**后续 agent 负责"唱戏"**（一次一个 feature）。

**Anthropic 的设计**：

| Agent | 时机 | 任务 |
|---|---|---|
| **Initializer Agent** | 第一次 session | 写 `init.sh`（起开发环境脚本）、`claude-progress.txt`（工作日志）、`feature_list.json`（feature 清单，所有 `passes: false`）、第一个 git commit |
| **Coding Agent** | 之后每个 session | 读 progress + features → 挑一个 feature → 写代码 → 测 → commit → 写 progress 更新 |

**关键限制**：**Coding Agent 只能改 feature 的 `passes` 字段**——不能增删 feature。prompt 写得**很强硬**："It is unacceptable to remove or edit tests"。

**面试可讲的角度**：这是 *separation of concerns*——**Initializer 是架构师（搭骨架），Coding Agent 是工人（一次填一块砖）**。**工人不能动架构**——这是制度设计，不是 prompt 设计。

**工程落地**：
- **两个 agent 用同一个 harness**（SDK + system prompt），只是 user prompt 不同。**不要让架构分叉**。
- **Coding Agent 的 prompt 里 hardcode**："**You can only change `passes` field**"——其他写法都会被模型找到擦边球路径。
- **Initializer 输出的三个文件**就是后续 agent 的"项目记忆"——**没有这三个文件，harness 等于裸跑**。

---

## 3. JSON Feature List：结构化 feature 强制 incremental

**一行定位**：**JSON 比 Markdown 不容易被模型偷改**——`passes: false` 强制 incremental 推进。

**Anthropic 的设计**：
- 200+ feature 的 JSON 清单，每个含 `category / description / steps / passes`。
- **全部初始化为 `passes: false`**。
- Coding Agent **只能改 `passes` 字段**——不能改 `description`、不能删 feature、不能增 feature。
- 实测：Markdown 版本容易被模型"优化"措辞、合并条目、删除"看起来重复"的——JSON 结构锁死了编辑动作。

**Feature 示例**（节选）：

```json
{
  "category": "functional",
  "description": "New chat button creates a fresh conversation",
  "steps": [
    "Navigate to main interface",
    "Click the 'New Chat' button",
    "Verify a new conversation is created",
    "Check that chat area shows welcome state",
    "Verify conversation appears in sidebar"
  ],
  "passes": false
}
```

**面试可讲的角度**：这是 *data integrity through schema*——**给数据严格 schema，模型就只能做允许的事**。比 prompt 限制靠谱，因为 prompt 是自然语言，模型会灵活解读。

**工程落地**：
- **用 JSON / YAML 而非 Markdown**——schema 限制改写空间。
- **Feature list 必须穷举**——200+ 不是过度，是必要**。**模型判断"哪些 feature 重要"会偏向 AI cliche 集**——强行列全才是 ground truth。
- **每个 feature 都有 steps 数组**——steps 是后续 testing agent / 自己的 checklist。

---

## 4. Clean State 协议：git commit + progress + init.sh

**一行定位**：**每个 session 结束必须留可继续的 codebase**——`git commit` + `progress notes` + `init.sh`，三件套缺一不可。

**Anthropic 的"clean state"定义**：
- 代码 **能 merge 到 main 分支**——没重大 bug、整洁、有文档。
- 下一个开发者（人或 agent）能直接开始新 feature，**不需要先清理无关混乱**。

**三个 artifact 的角色**：
- **`init.sh`**：一键重启开发服务器——Coding Agent 上手就能跑。
- **`claude-progress.txt`**：人类可读的工作日志——上一个 session 做了什么、为什么、下一个该做什么。
- **git commits**：原子、可 revert——**git 是真回回退工具**，prompt 是"我说要回退"。

**Coding Agent 行为闭环**：
1. 读 `claude-progress.txt` + `git log` → 理解上一 session
2. 跑 `init.sh` + 基础 e2e 测试 → **确认没遗留 bug**
3. 挑一个 feature → 写代码 → 测 → commit
4. 更新 `claude-progress.txt`

**面试可讲的角度**：这是 *state externalization*——**所有状态在 session 外**（git、文件、init 脚本）。**Agent 内部 context 是不可靠存储**（compaction 会丢），外部 artifact 是可信存储。

**工程落地**：
- **`init.sh` 必须 idempotent**——能跑多次。Agent 会反复调用。
- **`progress.txt` 写"为什么"**——"为什么放弃 X 方案"、"为什么用 Y 库"——这些是下一个 session 最缺的 context。
- **commit message 写 task 编号**——`#42 fix chat scroll bug`——让 git log 和 feature list 能 cross-ref。

---

## 5. Puppeteer MCP：让 Agent 真正"看到"功能 work

**一行定位**：**Unit test + curl 不够**——Agent 必须用 browser automation 像人一样测试。

**Anthropic 的发现**：
- 默认 Claude 改了代码 → 跑 unit test → `curl` 一下 dev server → **自我满意**，但**实际 browser 里坏掉**（modal 不显示、button 不响应、CSS 错位）。
- **显式提示 + Puppeteer 工具**后，Claude 能 screenshot → 看到 modal 没弹出 → **找到真 bug**。
- **但仍有局限**：Claude 视觉能力 + 浏览器自动化工具**看不到 browser-native alert modal**——依赖 modal 的功能 bug 率更高。

**改进效果**：**提供了 browser automation 工具后，end-to-end pass rate 显著提升**——能发现单看代码看不出的 bug。

**面试可讲的角度**：这是 *grounding through environment*——**模型对"功能 work"的定义是文本层面的**，**人类对"功能 work"的定义是体验层面的**。**只有让 Agent 进入体验环境，才能测体验**。

**工程落地**：
- **Coding Agent 必须有 Playwright/Puppeteer 工具**——CLI curl 不够。
- **每个 feature 完成 = screenshot + 自动化点击验证**——不只是 unit test pass。
- **承认 browser automation 有盲点**——modal、native dialog、键盘 shortcut 都难测。**这些地方要额外的 workaround**（例如在 prompt 里明确"用 screenshot 验证 modal 出现"）。

---

## Coding Agent 启动 5 步 checklist

每次新 session 开始时，Coding Agent 按顺序：

```bash
# 1. 看我在哪
pwd

# 2. 读工作日志
cat claude-progress.txt

# 3. 读 feature list
cat feature_list.json | jq '.features[] | select(.passes == false) | .description' | head

# 4. 看最近 commit
git log --oneline -20

# 5. 起服务 + 跑基础 e2e（确认没遗留 bug）
bash init.sh
# 用 Puppeteer 测：新 chat → 输消息 → 收到响应
```

**为什么这 5 步是 critical**：
- pwd → 路径错误 = 整个 session 走错方向。
- progress → 知道**为什么**上次这么做（不是只看 commit diff）。
- feature list → 不会"已经做完了"假象。
- git log → 知道已经做了什么。
- e2e test → **早发现遗留 bug，避免在新功能上叠加 bug**。

**面试可讲的角度**：这是 *defensive coding ritual*——**每次新 worker 上岗必须先验证环境干净**，不是开始干活。

## 一句话总结

长时 Agent harness 的本质是 **"双角色 + 三文件 + 五步启动协议"**——**Initializer 搭骨架、Coding Agent 填砖、git/progress/init.sh 是骨架、5 步启动是 ritual**。**这整套是把人类软件工程的最佳实践（commit message、progress notes、clean state、end-to-end testing）映射到 agent session 边界**。

## 配套阅读

- **同主题**：harness-design-gan-evaluator — 多 Agent + Generator-Evaluator 模式
- **执行机制**：claude-agent-sdk-engineering — Harness 抽象的 SDK 落地
- **评测视角**：demystifying-ai-agent-evals — 这种 harness 的 eval 怎么设计

参考资料：

- [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) — Justin Young, Anthropic
- [Claude Agent SDK quickstart](https://github.com/anthropics/claude-agent-sdk-python) — 代码示例
- [Claude 4 prompting guide](https://docs.claude.com/en/docs/build-with-claude/prompt-engineering) — 多 context window workflow