---
title: 让 Coding Agent 学会你的习惯：观察 + 提炼 + 注入的自学习闭环
date: 2026-09-15
tags: [AI Coding, Claude Code, Hook, 自学习, 记忆系统]
summary: 这篇不讲"AI 帮你写代码"，讲"AI 学会你写代码的方式"。核心是用 Hook 把工具调用 100% 抓成观测流，会话结束时用统计 + 语义两条路径提炼 Instinct 规则，下次会话 SessionStart 时把规则注入系统提示。三个环扣在一起，AI Coding Agent 才能从"工具"变成"伙伴"。
source-url: https://xie.infoq.cn/article/3daa13b4996b1be44a9425cfa
source-title: 让 Claude Code 拥有自我进化和记忆系统｜得物技术
source-author: 得物技术
---

## 原文在说什么

得物晴天这篇解决的是 Claude Code 的"失忆症"——每次开新对话，昨天解释过的项目架构、纠正过的代码风格偏好、建立的开发规范全部归零。OpenClaw 和 Hermes 已经具备持久化记忆系统，所以作者想：能不能给 Claude Code 装一套长期记忆？更进一步——**不是被动记忆，而是主动学习**，观察我的行为模式、项目架构，提炼行为规律，下次自动应用。

整套系统由三个核心子系统构成：**Observation Engine（行为观测层）、Instinct Engine（模式提炼层）、Memory Engine（记忆注入层）**。

**Observation Engine** 通过 Claude Code 原生 Hook 机制 100% 捕获每次工具调用，写入 JSONL 观测流。配置在 `~/.claude/settings.json`：

- `PreToolUse` matcher="Bash" → `observe.sh pre`（记录工具调用意图）
- `PostToolUse` matcher=".*" → `observe.sh post`（100% 采集所有工具后置事件）
- `Stop` → `auto-analyze-instincts.py` + `auto-evolve.py`（会话结束触发提炼流程）

作者明确提到：早期版本用 Skill 触发学习，触发率不稳定；改用原生 Hook 后彻底解决。**确定性触发是数据质量的保障**——放弃依赖模型主动调用是这条路能走通的关键。

每条观测记录是 JSONL 一行：包含 session_id、ts、phase（pre/post）、tool 名称、input 参数。当前已积累数万条观测记录、约 4MB 数据。为防膨胀，`observations_rotate.py` 在文件超 5MB 或 8000 行时按月份分片归档，主文件只保留最近 30 天。

**Instinct Engine** 会话结束时自动分析观测数据，提炼行为模式为原子化 Instinct 规则，置信度动态演化。提炼走两条并行路径：

- **路径 A：统计模式检测**——基于规则的硬编码检测器，识别高频工具调用序列（比如 Edit 前是否 Read、git 操作序列等）
- **路径 B：AI 语义分析**——调用 Claude Haiku 4.5 做语义理解，捕获统计模式无法识别的深层规律

每条 Instinct 是独立的 Markdown 文件，存 `~/.claude/homunculus/instincts/personal/`，用 YAML frontmatter：

```yaml
id: read-before-edit-pattern
trigger: "when about to edit a file that hasn't been read in this session"
confidence: 0.78
domain: workflow
source: session-observation
deprecated: false
observed_at: "2026-05-20"
```

**语义去重算法**有意思——单条 Instinct 原子化后，`auto-evolve.py` 用 Union-Find + Jaccard 相似度（阈值 0.5）合并同域高置信度规则，生成 Evolved Skill，**且只提取英文关键词计算 Jaccard**：用户可能用中文或英文描述同一习惯，基于英文技术词汇能跨语言识别同一意图。

去重后按 domain 分组（workflow 7 条、testing 3 条、git 2 条、code-style 2 条...），每组 ≥2 条才生成 Evolved Skill，最终合并成 `~/.claude/rules/auto-evolved.md`。**每次会话结束整体覆盖重写**，始终保持最新。Claude Code 启动时自动加载 rules 目录下所有 md，实现规则跨会话注入。

**Memory Engine** 处理知识性记忆——解决过的 Bug、技术决策、项目上下文。每条记忆是独立 Markdown 文件，YAML frontmatter 含 type（feedback / project / user 等）。

记忆召回链路分四阶段：

1. **触发时机**——`SessionStart` Hook 触发 `inject_memory_context.py`，**在第一条用户消息前就注入上下文**
2. **查询构造**——用当前工作目录（`$PWD`）+ 最近 3 条 git commit message 构造查询
3. **向量检索**——本地 nomic-embed-text 模型 + Qdrant 向量库，Top-5 余弦相似度召回
4. **上下文注入**——结构化 Markdown 注入系统提示，每条记忆带类型标签

作者选本地 Embedding 而非 Claude API 的原因：**记忆内容可能含项目路径、函数名等敏感信息**，上传云端存在隐私风险。nomic-embed-text 在 M 系列芯片推理约 10ms/条。

**实际效果**（数月真实使用数据）：

- 上下文冷启动 10 分钟 → 30 秒
- Token 消耗降低约 78%
- 错误重复率下降 80%
- 知识复利效应：第 1 个月 ROI 较低、第 3 个月十余条高置信度规则、第 6 个月数百条 Instinct 积累

## 我的看法

我认同作者把"Hook → 观测 → 提炼 → 注入"作为自学习闭环起点的判断。文章里最有工程价值的两个判断：

第一，**Hook 优先于 Skill**。这一条反直觉但很关键——Skill 依赖模型主动调用，触发率不稳定；Hook 是系统级回调，100% 触发。一个学习系统的数据质量完全取决于采集率，采集率上不去，再聪明的提炼算法也是 garbage in garbage out。这条原则可以推广到所有"Agent 自学习"系统：观测层必须是确定性的，不能依赖模型"记得调一下"。

第二，**规则注入必须在第一条消息之前**。`SessionStart` Hook 把记忆注入系统提示，是这条链路能产生价值的关键时机——用户第一条消息进来时上下文已经就绪。如果改成"用户问的时候才检索"会慢得多，且容易漏掉相关记忆。

但我有几个 push back：

第一，**置信度演化机制没说清楚**。文章说"反复观测强化，长期不触发衰减"——这是直觉上对的，但没量化。`confidence` 字段当前是固定值还是动态调整？如果是动态，调整算法是什么？这对 Instinct 库的健康度至关重要：一个错误规则被反复强化，就会污染所有会话。

第二，**Jaccard 相似度跨语言去重的边界**。作者说"只提取英文关键词"——这对技术术语有效，但中文项目里很多习惯是中文表达的（比如"先跑测试再 commit"），这些中文习惯完全被这套机制忽略了。一个更好的设计是 multilingual embedding 而非英文关键词 hardcode。

第三，**失败补偿没说**。如果 `auto-analyze-instincts.py` 在会话结束时崩溃了，observations 数据会越积越多但永远不会被提炼。这是定时任务 + 手动重试能解决的，但文章没说。

### 怎么落到 Agent 项目

如果让我基于这篇做一个**AI Coding Agent 的自学习子系统**，我会画成这样：

**核心模块四件套：Hook 适配器、观测流、规则提炼器、规则注入器。**

1. **Hook 适配器**：每个 Agent 平台都有自己的 hook 机制——Claude Code 是 settings.json、Cursor 是配置文件、Copilot 是 LSP。要做的是封装一层"工具调用生命周期"接口（pre/post/stop），让上层不感知具体平台。这是做通用 Agent 增强的关键。

2. **观测流**：JSONL 写入，**只在本机**，不送云端。包含 session_id、ts、phase、tool、input/output hash（注意：input/output 不送云端但可以做本地 hash 用于去重）。文件按 5MB/8000 行分片归档。

3. **规则提炼器**：两条路径并行——统计模式检测（硬编码高频序列）+ AI 语义分析（调用本地 LLM 或云端廉价模型）。Instinct 是原子 Markdown + YAML frontmatter。**Union-Find + Jaccard 去重**，阈值 0.5。Domain 聚合后生成 Evolved Skill。

4. **规则注入器**：`SessionStart` Hook 触发，把 `auto-evolved.md` 和 Top-5 记忆一起注入系统提示。**绝不在用户消息后才注入**——这是时机问题。

**工程上最值得做的：**

- **失败兜底**：提炼失败时把 observations 移到 `pending/` 目录，下次会话自动重试
- **置信度动态调整**：每次 Instinct 被"命中"（用户接受了基于它的建议）+0.05，"否定"（用户撤销了基于它的操作）-0.1，长期不触发 -0.02/月
- **隐私边界**：observations 仅本地；export 时只导出 Instinct 模式规则，不含代码路径和会话内容

**面试时被问"AI Coding Agent 怎么变得个性化"**——直接答 Hook + 观测 + 提炼 + 注入的自学习闭环。**真正的工程能力不在于这个闭环本身**，而在于：Hook 100% 触发率、失败重试、置信度演化、跨语言去重、隐私边界——把这五件事做出来，Coding Agent 才从"工具"变成"伙伴"。

## 一句话总结

AI Coding Agent 学会你的习惯，不是靠更大模型，而是靠一个确定性的观测—提炼—注入闭环；Hook 触发率是数据质量的命门，SessionStart 注入时机是价值兑现的命门。