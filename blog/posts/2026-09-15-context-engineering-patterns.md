---
title: Context Engineering 实操：让 LLM 注意力预算花在刀刃上的 6 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, Context Engineering, Agent]
summary: 把 Anthropic Effective Context Engineering 文章拆成 6 个工程模式：Context Rot 与注意力预算、System Prompt 的 right altitude、Tools 的最小可用集、Just-in-time retrieval、长任务三件套（compaction / note-taking / sub-agents）、Hybrid 策略（upfront + JIT）。配 code 示例 + 面试可讲的设计取舍 + 落地 checklist。
source-url: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
source-title: Effective context engineering for AI agents
source-author: Prithvi Rajasekaran, Ethan Dixon, Carly Ryan, Jeremy Hadfield (Anthropic Applied AI)
---

## 引子

Prompt engineering 已经过时——Anthropic 把"该往 LLM context 里塞什么"的整体学科重新命名为 **Context Engineering**。这一篇是 Anthropic 对"怎么用 LLM 注意力预算"的整套方法论：**Context 是有限资源（attention budget）、System Prompt 要在 right altitude、Tools 要 minimal viable set、长任务三件套 compaction/note-taking/sub-agents、Just-in-time retrieval 优于 pre-computed**。

下面拆 6 个工程模式，按"**为什么 → 系统 prompt → tools → 检索 → 长任务 → hybrid**"递进。

---

## 1. Context Rot：LLM 注意力是有限资源

**一行定位**：**Context window 不是 unlimited bag——token 越多，每个 token 分到的注意力越少**。**Context 是有 diminishing returns 的稀缺资源**。

**Anthropic 的数据**：
- "Needle in a haystack" benchmark：context 越长，**模型精确回忆的能力下降**。
- 所有模型都有这特性——有些温和、有些剧烈，**没有不存在的**。
- 根因：transformer 是 n² pairwise attention——**n tokens = n² 个关系对**，关系越多注意力越薄。
- 模型训练数据中短序列多、长序列少——**模型对长 context-wide dependency 的"参数经验"本来就少**。

**面试可讲的角度**：这是 *working memory* in cognitive science——**人脑短时记忆 ~7 items**，LLM 注意力类似。**别把 context 当 unlimited hard drive，当 scarce working memory 用**。

**工程落地**：
- ☐ **不要试图把所有信息塞 context**——每加一个 token 都该问"这 token 真的必要吗？"
- ☐ **监控 context 使用率**——> 60% 就要开始 compaction
- ☐ **理解 context rot 不可避免**——**正面对待而不是忽视**
- ☐ **架构层面减少 noise**——clean schema / clear tool descriptions / structured examples

---

## 2. System Prompt 的 Right Altitude：具体但不 brittle

**一行定位**：**System Prompt 不是 if-else 硬编码，也不是 vague 高层指引**——**在"具体到能指导行为 + 灵活到能 generalize"的 sweet spot**。

**Anthropic 的两个反模式**：
- **Too low**：hardcode if-else logic——"if user says X, then call tool Y"——**fragile、maintenance nightmare**。
- **Too high**：vague 指引——"be a helpful assistant"——**没有 signal 给模型，falsely assume shared context**。

**Right altitude**：
- 用 XML tags / Markdown headers 分 section：`<background_information>` `<instructions>` `## Tool guidance` `## Output description`。
- 具体到**告诉模型做事的原则**，不具体到**每一步做什么**。
- 例子比规则更有用——**few-shot canonical examples > rule list**。
- **从 minimal prompt + 最强模型开始**，再根据 failure mode 加 instruction。

**面试可讲的角度**：这是 *concrete vs abstract* 的工程权衡——**抽象让代码长寿，具体让代码当下正确**。**right altitude 是兼顾**：**现在能跑、未来能改**。

**工程落地 checklist**：
- ☐ **分 section**——background / instructions / tool guidance / output description
- ☐ **写 canonical examples**（3-5 个 diverse）——**不是 edge case 列表**
- ☐ **避免 if-else 硬编码**——**写原则不写步骤**
- ☐ **定期 review prompt**——模型变强后过度 specific 的 prompt 是 dead weight（见 harness-design-gan-evaluator 的元教训）

---

## 3. Tools：最小可用集 + 清晰目的

**一行定位**：**Tools 是 agent 和 环境之间的关系的契约**——**Tool 集合越 bloated，agent 决策越 ambiguous**。

**Anthropic 的判断标准**：
- **"人类工程师都没法决定用哪个 tool 时，AI agent 更不行"**。
- **Tool 集合要 minimal viable set**——能 cover 任务，不多一个。
- **Tool 之间不重叠**——`create_ticket` vs `create_incident` 这种相似的让 agent 迷茫。
- **Tool input parameter 描述性 + 不歧义**——用 model 擅长的参数类型（`status: enum["active", "paused"]` 而不是 magic string）。

**Few-shot examples 加在 tool definition**（见 advanced-tool-use-three-features）：**schema 说"语法"，examples 说"惯用法"**——accuracy 72% → 90%。

**面试可讲的角度**：这是 *API design* in LLM era——**tool definition 是给 LLM 看的 API doc**。**好的 API 是 obvious to use**。**Tool design 质量决定 agent 上限**。

**工程落地**：
- ☐ **每个 tool 有明确单一目的**——不要 `manage_user` 这种大杂烩
- ☐ **Tool 描述写"什么时候用"**——不是"做什么"，是"trigger condition"
- ☐ **相似 tool 合并或拆分**——重复功能让 agent 选错
- ☐ **Tool examples 加 few-shot**——schema 表达不出的"惯用法"用 example 教

---

## 4. Just-in-Time Retrieval：让 Agent 自己找 Context

**一行定位**：**不要 pre-compute 所有 relevant data**——**给 Agent lightweight identifiers（file path / stored query / URL），让它自己 fetch**。

**传统做法的问题**：
- Embedding-based RAG 提前把所有 relevant 文档 retrieve → context。
- **问题是 stale indexing、complex syntax tree、过度 retrieve**。

**Just-in-time 做法**：
- Agent 持有 lightweight identifier（file path, stored query, web link）。
- 用 tools (`Read`, `Bash head/tail`, `Grep`, `Glob`) **动态加载**。
- **类比**：人脑不背 corpus，靠文件系统 / 书签 / inbox 当 external memory。

**优势**：
- **没有 stale index 问题**——filesystem 永远新鲜。
- **Progressive disclosure**——Agent 探索 → 发现需要更多 → 再 fetch。
- **Metadata 也是 context**——file size（暗示复杂度）、filename convention（暗示用途）、timestamp（暗示相关度）。

**Anthropic 的"hybrid strategy"**：
- **CLAUDE.md** upfront 加载——团队规则、稳定 context。
- **`Glob` / `Grep`** JIT 探索——filesystem navigation 不需要预 computed index。
- **混合**：稳定的东西 upfront + 动态的东西 JIT。

**面试可讲的角度**：这是 *von Neumann architecture*——**程序 vs 数据分离**。**pre-computed retrieval 是把"知识"塞进 context（程序），JIT 是让 context 里只有"指针"（数据）**。**数据随时变，程序稳定**。

**工程落地**：
- ☐ **Context 里只放 identifier**（file path / query / URL），不放 raw data
- ☐ **Tool 让 Agent fetch**——`Read` / `Bash head` / `WebFetch` 必须 available
- ☐ **Metadata 给 model signal**——filename convention / folder hierarchy / timestamp
- ☐ **不追求 100% pre-computed**——**stable 走 upfront，dynamic 走 JIT**

---

## 5. 长任务三件套：Compaction / Note-taking / Sub-agents

**一行定位**：**长任务必然超 context window**——**用 compaction、note-taking、sub-agents 三种工程策略扩展**。

### Compaction（压缩）
- 把快到 context limit 的对话 summary，**新开 context 用 summary 启动**。
- **艺术在于"什么保留 / 什么丢弃"**——**先 maximize recall，再 iterate precision**。
- **Low-hanging 起点**：清掉 tool call/result 的 raw output——deep history 里的 tool result 不需要再让 agent 看。

**Claude Code 实践**：让 model 自己总结 message history → 保留 architectural decisions、unresolved bugs、implementation details → 丢弃 redundant tool outputs → 加最近 5 个文件。

### Note-taking（结构化笔记）
- Agent 定期写笔记到 context 外（NOTES.md / memory tool）。
- 下次 session 读笔记 + 继续。
- **例子**：Claude 玩 Pokémon 维持精确计数（"Pikachu 还差 2 级到目标 10"）+ 区域地图 + 战斗策略笔记。
- **跨 session 持久**：session 结束 → 写文件；session 开始 → 读文件。

**关键 insight**：**Note-taking 是 Agent 的"外脑"**——**context 里只放 working set，外部文件当 long-term memory**。

### Sub-agents（多 Agent）
- 每个 sub-agent 有**自己的干净 context window**。
- Main agent 持 plan，sub-agent 跑 deep work。
- **Sub-agent 返回 condensed summary**（1-2K tokens），不是 raw exploration（10K+ tokens）。
- **清晰 separation of concerns**——detail search context 在 sub-agent 里，main agent 只 synthesize。

**Trade-off 表**：

| 策略 | 适合场景 | 不适合 |
|---|---|---|
| **Compaction** | 多轮对话、需要 conversational flow | 单次决策、dense 数据 |
| **Note-taking** | iterative development with milestones | 单调 one-shot 任务 |
| **Sub-agents** | 复杂 research / 大量 parallel exploration | 强 sequential 任务 |

**面试可讲的角度**：这是 *distributed systems* 的工程类比——**compaction 像 log compaction、note-taking 像 persistent storage、sub-agents 像 microservices with bounded context**。**问题域一样：单机装不下 → 拆 + 边界**。

**工程落地**：
- ☐ **长任务开始就 plan**——"我会用哪种策略？" 不要等到 context 满了再慌
- ☐ **Note-taking 用 structured format**——JSON / Markdown table，**别让 model 自由发挥**
- ☐ **Sub-agent 必须 narrow scope**——给它一个明确 deliverable，不是"帮我研究 X"
- ☐ **Compaction prompt 优先 recall 再 precision**——**missing 关键信息比 verbose 更糟糕**

---

## 6. Hybrid 策略：稳定 upfront + 动态 JIT

**Anthropic 的官方建议**：**不要 all-JIT 也不要 all-upfront——按 context stability 切**：

| Context 类型 | 策略 | 例子 |
|---|---|---|
| **稳定 + 全局相关** | Upfront | CLAUDE.md（团队规则） |
| **大但稳定** | Upfront 部分 + 引用 | API schema（部分进 prompt，详细 schema 走 link） |
| **动态 / 个别相关** | JIT | Database content / specific file / web page |
| **常变 + 时效** | JIT | Git history / 实时 API response |

**Claude Code 是 hybrid 的典范**：
- CLAUDE.md → 全局规则 upfront。
- Glob / Grep / Bash → filesystem JIT。
- Agent 决定何时 load 哪个。

**给不同领域的建议**：
- **法律 / 金融**（低动态）——**多 upfront**，**少 JIT**——这些领域 context 稳定。
- **代码 / research**（高动态）——**多 JIT**，**少 upfront**——这些 context 时时变。

**面试可讲的角度**：这是 *caching strategy* 的工程应用——**stable data cache 起来，dynamic data 实时 fetch**。**类比 CDN + dynamic API**。

**工程落地**：
- ☐ **绘制 context 分类表**——stable vs dynamic、global vs per-task
- ☐ **稳定 + 全局 → upfront**（CLAUDE.md / system prompt）
- ☐ **稳定 + 按需 → reference link / progressive disclosure**
- ☐ **动态 → JIT via tools**
- ☐ **不要全 upfront**——浪费 token + stale 风险
- ☐ **不要全 JIT**——agent 不知道什么时候找什么

---

## 一句话总结

Context Engineering 是**"把 LLM 当稀缺注意力预算来花"的整套方法论**——**right altitude 的 system prompt、minimal viable tools、JIT retrieval 替代 pre-computed、长任务三件套（compaction/note-taking/sub-agents）、hybrid stable/dynamic 切分**。**Context 是有限资源，不是 unlimited bag——每加一个 token 都该问"值得吗？"**

## 配套阅读

- **同主题**：agent-skills-progressive-disclosure — Skill 是 context 的 progressive disclosure 实现
- **执行机制**：tool-use-engineering-patterns — tool 设计即 context 设计
- **架构视角**：managed-agents-arch-patterns — Session 是 durable context 的工程实现

参考资料：

- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — Prithvi Rajasekaran et al., Anthropic
- [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) — Agent vs workflow 的边界
- [Memory tool cookbook](https://github.com/anthropics/claude-cookbooks) — Note-taking 的工程示例