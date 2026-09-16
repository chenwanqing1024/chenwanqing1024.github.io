---
title: Claude Code 实战：把 Coding Agent 用出 10x 效率的 6 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, Claude Code, Agent]
summary: 把 Anthropic Claude Code Best Practices 官方文档拆成 6 个工程模式：Verify 工作流（测试 / build / screenshot 是 must-have）、Explore→Plan→Code→Commit 四段、CLAUDE.md 极简主义、Permission + Sandbox + Auto mode 三层防御、Context 主动管理（/clear / /compact / subagent）、Parallel Sessions + Fan-out + Adversarial Review 扩展模式。配具体命令 + 失败模式 + 面试可讲的设计取舍。
source-url: "https://code.claude.com/docs/en/best-practices"
source-title: Best practices for Claude Code
source-author: Anthropic
---

## 引子

Claude Code 不是"另一个 chat-with-code 工具"——**它是 agentic coding environment**——**Claude 自己 explore、plan、implement**，**你 watch、redirect、or step away entirely**。**这改变工作模式**——**不是"你写 + Claude review"，是"你描述 + Claude build"**。**但 autonomy 有 learning curve**——**你必须理解约束才能用好**。Anthropic 官方 best practices 文档的 6 个工程模式——**核心论点是 context window 是核心资源，verify 是 must-have，配置 / prompt / 工作流 三层都需要 discipline**。**这是 2025 年 coding agent 的官方权威指南**。

下面拆 6 个工程模式，按"**verify → 工作流 → 配置 → 权限 → context → 并行**"递进。

---

## 1. Verify 工作流：测试 / Build / Screenshot 是 Must-Have

**一行定位**：**没有 verify loop = 你就是 verification loop**——**Claude 做完不知道对不对，全靠你人肉 check**。

**Anthropic 的核心论点**：

> "Give Claude a check it can run: tests, a build, a screenshot to compare. It's the difference between a session you watch and one you walk away from."

**Claude 行为模式**："Claude stops when the work looks done. Without a check it can run, 'looks done' is the only signal available."

**Verify 的 4 个层次**（从最简单到最强）：

| 层次 | 机制 | 适用 |
|---|---|---|
| **In-prompt** | 一句话让 Claude 自己 run + iterate | 任何任务 |
| **`/goal` condition** | 跨 session 持续 check，Claude auto iterate | unattended runs |
| **Stop hook** | deterministic script gate stop | 必须通过才结束 |
| **Adversarial review** | 独立 subagent 找 gap | 重要改动 |

**Verify 形式**（any 都能用）：
- **Test suite**（unit / integration）。
- **Build exit code**。
- **Linter / type check**。
- **Diff script against fixture**。
- **Browser screenshot** 对比 design。

**Good vs Bad prompt 对比**：

| ❌ Before | ✅ After |
|---|---|
| "implement a function that validates email addresses" | "write a validateEmail function. example test cases: user@example.com is true, invalid is false, user@.com is false. run the tests after implementing" |
| "make the dashboard look better" | "[paste screenshot] implement this design. take a screenshot of the result and compare it to the original. list differences and fix them" |
| "the build is failing" | "the build fails with this error: [paste error]. fix it and verify the build succeeds. address the root cause, don't suppress the error" |

**面试可讲的角度**：这是 *closed-loop automation*——**有 verify loop = Claude 自己 iterate**，**没 verify = 你 manual iterate**。**类比 CI**——CI 没跑 = 你人肉测。**Verify 是 coding agent 时代的 unit test**。

**工程落地**：
- ☐ **每个 task 必配 verify 手段**——**没 verify 的 task 不要 ship**
- ☐ **Verify 形式选最便宜的**——test > build > screenshot（screenshot 贵）
- ☐ **`/goal` 适合 unattended**——**long-running task 让 Claude 自己 iterate**
- ☐ **Stop hook 适合 critical gate**——migration / schema change

---

## 2. Explore → Plan → Code → Commit 四段工作流

**一行定位**：**让 Claude 直接 code = solve 错问题**——**Explore / Plan / Code / Commit 四段分离避免 wasted work**。

**4 阶段工作流**：

### Stage 1: Explore（plan mode 读 + 理解）

- **按 `Shift+Tab` 进 plan mode** 或 `claude --permission-mode plan`。
- Claude **只读不写**——读文件 + 答问题 + 不改任何东西。
- Example prompt：
  ```
  read /src/auth and understand how we handle sessions and login.
  also look at how we manage environment variables for secrets.
  ```

### Stage 2: Plan（写详细 implementation plan）

- 在 plan mode 让 Claude **写 detailed plan**。
- **按 `Ctrl+G` 在文本编辑器打开 plan**——**你可以直接编辑**。
- Example prompt：
  ```
  I want to add Google OAuth. What files need to change?
  What's the session flow? Create a plan.
  ```

### Stage 3: Implement（按 plan code + verify）

- **退出 plan mode**（approve plan 或 `Shift+Tab`）。
- Claude 按 plan code + 跑 test + 修。
- Example prompt：
  ```
  implement the OAuth flow from your plan. write tests for the
  callback handler, run the test suite and fix any failures.
  ```

### Stage 4: Commit（commit + PR）

- 让 Claude commit + push + open PR。
- Example prompt：
  ```
  commit with a descriptive message and open a PR
  ```

**什么时候 skip plan**：
- ✅ **Task 简单明确**——typo / log line / rename。
- ✅ **Diff 能一句话描述**——"if you can describe the diff in one sentence, skip the plan"。

**什么时候用 plan**：
- ⚠️ **不确定 approach**。
- ⚠️ **改多个文件**。
- ⚠️ **不熟悉被改的 code**。

**面试可讲的角度**：这是 *separation of concerns*——**Explore / Plan / Code / Commit 各自的 mental mode 不同**。**类比 TDD**：red / green / refactor 三段分离。**Coding agent 也需要 phase separation**。

**工程落地**：
- ☐ **默认进 plan mode**——**不是默认直接 code**
- ☐ **Plan 文件存到 git**——**review + iteration 持久化**
- ☐ **Plan 必含 verify step**——**end-to-end verification 是 plan 的最后一步**
- ☐ **小 task skip plan**——**但大 task 必 plan**

---

## 3. CLAUDE.md 极简主义：每行必问"删了会错吗？"

**一行定位**：**CLAUDE.md 是 Claude 每次 session 都读的 persistent context**——**bloat 越大，关键 rule 越被忽略**。

**Anthropic 的关键论断**：

> "If Claude keeps doing something you don't want despite having a rule against it, the file is probably too long and the rule is getting lost."

**起手**：`/init` 帮你从 project structure 生成 starter CLAUDE.md。**然后精炼**。

**Good CLAUDE.md 示例**：

```markdown
# Code style
- Use ES modules (import/export) syntax, not CommonJS (require)
- Destructure imports when possible (eg. import { foo } from 'bar')

# Workflow
- Be sure to typecheck when you're done making a series of code changes
- Prefer running single tests, and not the whole test suite, for performance
```

**Include vs Exclude 决策表**：

| ✅ Include | ❌ Exclude |
|---|---|
| Claude 猜不到的 Bash 命令 | Claude 能从 code 读出来 |
| 与默认不同的 code style | 标准 language convention |
| Testing instruction + preferred runner | 详细 API doc（用 link） |
| Repo etiquette（branch / PR 约定） | 频繁变的信息 |
| 特定 architectural decision | 冗长 explanation / tutorial |
| 常见 gotcha | 自我说明的 practice（"write clean code"） |

**调试 CLAUDE.md 的 3 个症状**：
- **Claude 老做你不要的事** → **file 太长，关键 rule 被 noise 淹没**。
- **Claude 问 CLAUDE.md 答过的事** → **phrasing ambiguous**。
- **Specific instruction 被忽略** → **加 "IMPORTANT" emphasis**——但不要全加，**全是 IMPORTANT = 没人重要**。

**CLAUDE.md 维护纪律**：
- ☐ **Git version control**——**team 共同维护**。
- ☐ **定期 prune**——`/doctor` 让 Claude 建议 cuts。
- ☐ **复杂 rule 转 hook**——**rule 不断违反 = 转 deterministic hook**。
- ☐ **Domain-specific 走 skill**——**CLAUDE.md 只放 broadly applicable**。

**面试可讲的角度**：这是 *signal-to-noise ratio*——**CLAUDE.md 是 high-signal 文件**。**bloat = noise = lost rules**。**类比 README**——README 太长没人读，CLAUDE.md 一样。**每行必 question："删了会错吗？"**。

**工程落地**：
- ☐ **CLAUDE.md 保持 < 100 行**——**超过就要 prune**
- ☐ **每行 include 必 answer 三个问题**："删了会错？/ 不能从 code 推？/ 不会变？"
- ☐ **Specific rule 配 "IMPORTANT"**——**但 limited 数量**
- ☐ **Domain rule 拆到 skill**——**CLAUDE.md 不放 infrequently relevant**

---

## 4. 权限 + Sandbox + Auto Mode 三层防御

**一行定位**：**Manual mode 弹窗疲劳、permission allowlist 减干扰、sandbox 隔离、auto mode AI 判断**——**四档 trade-off**。

**4 档权限模型**：

| 模式 | Claude 自主 | 人类审核 | 适用 |
|---|---|---|---|
| **Manual** | 不改 | 弹 confirm | 谨慎 / 不可逆操作 |
| **Permission allowlist** | allowlist 内自主 | 其他弹 confirm | 日常 dev |
| **Sandbox** | allowlist 内自主 | sandbox 边界拦 | 高自由度 |
| **Auto mode** | AI classifier 判断 | AI block risky | unattended |

**配置命令**：
- `/permissions`——**配 allowlist**（如 `npm run lint` / `git commit`）。
- `/sandbox`——**启 OS-level 隔离**（filesystem + network）。
- `claude --permission-mode auto -p "fix all lint errors"`——**auto mode + non-interactive**。

**Manual mode 的痛点**：

> "After the tenth approval you're clicking through rather than reviewing. Two tools cut those interruptions in Manual mode..."

**两件减干扰工具**：
1. **Permission allowlist**——**白名单内 no-prompt**。
2. **Sandboxing**——**sandbox 边界自动拦**（见 claude-code-sandboxing-isolation）。

**Auto mode 机制**（见 auto-mode-defense-architecture）：
- **Classifier model** 提前 review 命令。
- **Block scope escalation** / **unknown infrastructure** / **hostile-content-driven actions**。
- **Routine work no prompt**。
- **Auto mode + `-p` non-interactive**——**不弹窗，不停 run**。

**面试可讲的角度**：这是 *defense in depth*——**单层防御都有 edge case**。**手动 + allowlist + sandbox + auto classifier**——**每层独立 + 一起 = 纵深防御**。**安全设计 = 减摩擦 + 增安全**（Anthropic 数据 sandbox 降 84% prompt）。

**工程落地**：
- ☐ **日常 dev 配 allowlist**——**不要每次手动 approve**
- ☐ **Production 操作 manual mode**——**不可逆 = human 必须看**
- ☐ **Unattended run 配 sandbox + auto mode**——**双层防御**
- ☐ **`--allowedTools` 配 fan-out**——**每个 invocation scope 清楚**

---

## 5. Context 主动管理：/clear / /compact / Subagent

**一行定位**：**Context window 是核心资源**——**满 = 性能下降 + 早 instructions 忘**——**主动管理是必备 skill**。

**Anthropic 的核心论断**：

> "Most best practices are based on one constraint: Claude's context window fills up fast, and performance degrades as it fills."

**Context 管理的 4 个工具**：

### 5.1 `/clear` —— 任务间重置

- **任务不相关时用**——**上一个 task 的 context 完全 irrelevant**。
- 频率：**between tasks**——**不是 with 同一个 task**。

### 5.2 `/compact` —— 自动 + 手动压缩

- **Auto compaction**——**context 接近 limit 时自动 trigger**，summarize 历史。
- **Manual compaction**——`/compact <instructions>` 主动 trigger + 引导方向。
- **Example**：`/compact Focus on the API changes`——**让 compaction 保你想保的**。

### 5.3 `/rewind` + `Esc Esc` —— 部分压缩

- **`Esc + Esc`** 或 `/rewind`——**打开 rewind menu**。
- 选 checkpoint message：
  - **Summarize from here**——**从这点 forward 压缩，前 keep 完整**。
  - **Summarize up to here**——**前面压缩，后 keep 完整**。
- **比 `/clear` 灵活**——**只清一半**。

### 5.4 Subagent —— context 隔离

- **Research / exploration 用 subagent**——**main conversation context 保持 clean**。
- **Example prompt**：
  ```
  Use subagents to investigate how our authentication system handles token
  refresh, and whether we have any existing OAuth utilities I should reuse.
  ```
- **Subagent context 不进 main**——**only summary back**。

**Context 性能信号**：
- **Context 满**→ Claude "forget" 早 instruction + mistake 变多。
- **Status line 监控**——`/context` 查 current usage。
- **/btw** 适合不需要进 history 的问题——**answer 不入 context**。

**面试可讲的角度**：这是 *working memory management*——**类比人脑短时记忆 ~7 items**。**LLM 一样——context 是稀缺资源**。**主动 /clear + /compact + subagent**——**类比 GC + off-heap storage**。**不管理 = performance cliff**。

**工程落地**：
- ☐ **不同 task 之间 `/clear`**——**避免 irrelevant context 污染**
- ☐ **改 2 次以上还不 work → `/clear` + better prompt**——**failed approach 占 context 反而有害**
- ☐ **Investigation 用 subagent**——**main conversation 保持 focused**
- ☐ **CLAUDE.md 配 compaction guidance**——`"When compacting, preserve modified files + test commands"`

---

## 6. Parallel Sessions + Fan-out + Adversarial Review

**一行定位**：**一个 Claude 不够 = parallel sessions / fan-out / adversarial review**——**scale out 是 10x productivity 的来源**。

### 6.1 Multiple Claude sessions 并行

**Anthropic 官方支持的多种并行方式**：

| 模式 | 机制 | 适用 |
|---|---|---|
| **Worktrees** | 独立 git checkout，不撞 edit | 复杂多 branch |
| **Cross-session messaging** | sessions 之间手动传 finding | 协作 |
| **Desktop app** | UI 管理多 sessions | 视觉管理 |
| **Claude Code on the web** | Cloud session（Anthropic infra） | 不想本地 |
| **Agent view** | 后台跑 + 屏上看 | 长期 background |
| **Agent teams** | 自动 coordination | 复杂多 task（experimental） |

**Writer/Reviewer 模式**（**最经典**）：
- Session A 写 code。
- Session B 用 fresh context 审。
- Fresh context 不会 bias toward "我刚写的 code"。

```
Session A: "Implement a rate limiter for our API endpoints"
Session B: "Review the rate limiter implementation in @src/middleware/rateLimiter.ts.
            Look for edge cases, race conditions, and consistency with our existing
            middleware patterns."
Session A: "Here's the review feedback: [Session B output]. Address these issues."
```

**面试可讲的角度**：这是 *code review 的 anti-bias 设计*——**写 code 的人审自己 = bias**。**Fresh context 审 = independent judgement**。**类比：为什么 CR 不能自己 approve 自己的 PR**。

### 6.2 Fan out across files

**机制**：`/batch <instruction>` 让 Claude 把 change 拆到 5-30 subagents，每个 worktree + 自己的 PR。

**手动版**（用 `claude -p` 写 loop）：
```bash
# Step 1: 让 Claude 写 file list
claude -p "list all 2,000 Python files that need migrating and save the list to files.txt"

# Step 2: 写 loop script
for file in $(cat files.txt); do
  claude -p "Migrate $file from Python 2 to Python 3. Return OK or FAIL." \
    --allowedTools "Edit,Bash(git commit *)"
done

# Step 3: 试 2-3 个 file → 调 prompt → 跑全量
```

**工程要点**：
- ☐ **`--allowedTools` scope permissions**——**unattended 必 narrow scope**
- ☐ **先 2-3 file 试 → 调 prompt**——**避免 2000 file 全错**
- ☐ **`/batch` 自动 fan-out**——**适合 git repo 内的 migration**

### 6.3 Adversarial review step

**机制**：**让独立 subagent 审 diff**——**fresh context，only see diff + criteria**。

**Example prompt**：
```
Use a subagent to review the rate limiter diff against PLAN.md. Check that
every requirement is implemented, the listed edge cases have tests, and
nothing outside the task's scope changed. Report gaps, not style preferences.
```

**Anthropic 的"reviewer 必 instruct 找 gap"警告**：

> "A reviewer prompted to find gaps will usually report some, even when the work is sound... Chasing every finding leads to over-engineering."

**工程准则**：
- ☐ **只 flag 影响 correctness / 明确 requirements 的 gap**。
- ☐ **Style preference 标 optional**——**别 over-engineer**。
- ☐ **Subagent review 完，implementing session 收到 gap 直接 fix**——**省去 copying between windows**。

**面试可讲的角度**：这是 *adversarial validation*——**类比 GAN**——**generator 写 code，discriminator 找 gap**。**Independent check 比 self-review 强 10x**——**fresh context = no bias**。**生产 critical 改动必上 adversarial review**。

**工程落地 checklist**：
- ☐ **Critical 改动用 Writer/Reviewer 双 session**——**fresh context review**
- ☐ **Migration 用 fan-out + scope permissions**——**`--allowedTools` 必 narrow**
- ☐ **先 2-3 sample 调 prompt**——**避免大批量全错**
- ☐ **Reviewer prompt 必 instruct "only correctness gap"**——**别 over-engineer**

---

## 7 个常见失败模式

**Anthropic 列的 failure pattern**——**早期识别省时间**：

### Failure 1: Kitchen sink session（万用 session）

- **Symptom**：开 session 干 task A → 中途问 unrelated question → 回到 task A。
- **Context 满 irrelevant info**。
- **Fix**：`/clear` between tasks。

### Failure 2: Correcting over and over（反复纠正）

- **Symptom**：Claude 做错 → 你纠正 → 还错 → 再纠正。
- **Context 满 failed approaches**。
- **Fix**：**2 次失败后 `/clear` + better initial prompt**（incorporate what you learned）。

### Failure 3: Over-specified CLAUDE.md（CLAUDE.md 过长）

- **Symptom**：CLAUDE.md 长，**重要 rule 淹没在 noise**。
- **Claude 忽略 half of it**。
- **Fix**：**ruthlessly prune**——**已经做的对就别 rule**。**必要 rule 转 hook**。

### Failure 4: Trust-then-verify gap（信任不验证）

- **Symptom**：Claude 出 plausible-looking implementation，**不处理 edge case**。
- **Fix**：**always provide verification**（test / script / screenshot）。**不能 verify = 不 ship**。

### Failure 5: Infinite exploration（无限探索）

- **Symptom**："investigate X" 不 scope → Claude 读 hundreds of files → context 满。
- **Fix**：**narrow scope** + **subagent for investigation**（main context 保持 clean）。

### Failure 6: 跳过 verification gate

- **Symptom**：没 verify loop，**你手点 confirm 直到放弃**。
- **Fix**：**stage 1 verify loop 必上**。

### Failure 7: 长期 session 不管理 context

- **Symptom**：session 跑很久，**context 满 irrelevant**。
- **Fix**：**/clear 任务间** + **/compact long-running** + **subagent for research**。

**工程落地**：
- ☐ **每个 failure 模式配 detection signal**——**识别快 + 修得快**
- ☐ **/clear 是高频工具**——**不要等 context 满才清**
- ☐ **Verification 是 shipping 的硬门槛**——**没 verify 不 done**

---

## 一句话总结

Claude Code best practices 的核心论点是**"context window 是核心资源，verify loop 是必须，配置 / 工作流 / prompt 三层都要 discipline"**——**Verify 工作流（test / build / screenshot）+ Explore→Plan→Code→Commit 四段分离 + CLAUDE.md 极简主义（每行必问"删了会错吗"）+ 权限 / sandbox / auto mode 三层防御 + Context 主动管理（/clear / /compact / subagent）+ Parallel sessions + Fan-out + Adversarial review 扩展**。**6 个工程模式不是孤立技巧，是 "把 agent 用出 10x 效率" 的系统方法论**。**Anthropic 自己说"develop your intuition"——模式是起点，不是教条**。

## 配套阅读

- **同主题**：auto-mode-defense-architecture — reasoning-blind classifier 是 auto mode 核心
- **同主题**：claude-code-sandboxing-isolation — filesystem + network 双隔离
- **执行机制**：tool-use-engineering-patterns — tool choice / parallel / structured output

参考资料：

- [Best practices for Claude Code](https://code.claude.com/docs/en/best-practices) — Anthropic
- [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works) — Agentic loop 内部机制
- [Extend Claude Code](https://code.claude.com/docs/en/extend-claude-code) — Skills / hooks / MCP / subagents
- [Claude Code overview](https://www.anthropic.com/claude-code) — 官方主页
