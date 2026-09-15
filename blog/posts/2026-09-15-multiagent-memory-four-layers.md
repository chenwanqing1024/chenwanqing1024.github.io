---
title: Agent 记忆不是 prompt 拼接：四层架构与异步沉淀
date: 2026-09-15
tags: [Agent, 记忆系统, MemOS, 工程落地]
summary: 这篇不讲"把历史塞进 prompt"——它讲怎么把记忆拆成 Working / Session / User / Agent 四层，让请求前并行加载、会话后异步沉淀、用 LLM 判断价值、用冲突处理保持一致。四层不是分类维度的炫技，是把"Agent 记不住东西"这个老大难问题拆成可工程化的子问题。
source-url: https://xie.infoq.cn/article/29f870b888dc584ac1f9e96f7
source-title: 企业级 MultiAgent 的记忆系统：短期上下文与四层记忆架构实现｜得物技术
source-author: 得物技术
---

## 原文在说什么

得物这篇把"Agent 记忆"从一个含糊词变成一张可施工的图。

文章开篇就反对一种最常见的工程偷懒——把全部历史拼到 prompt。理由是 Agent 一次请求要经过模型、MCP/A2A 工具、RAG、Workflow 和 Sandbox 五个环节，多轮对话和跨会话协作还要记用户偏好、任务进展、协作约定。记忆不是外挂，是执行链路的一部分。

作者选了 **MemOS**（1540 题评测综合 74.33%，单跳多跳均达标）作为长期记忆引擎。后端 Spring Boot 3 + Java 17，Agent 编排用 AgentScope。新建 Agent 默认 `longMemoryProvider=MEMOS`，但 `openLongMemory` 默认关闭——开了之后，请求开始时短期会话历史和长期记忆**并行加载**，会话结束后由 `onSessionEndAsync` 异步完成筛选、去重和长期沉淀。

**四层记忆模型**对应四个生命周期：

- **Working Memory** 只服务当前一步推理，掉电即丢
- **Session Memory** 保存会话内消息历史，是代词消解和多轮推理的上下文
- **User Memory** 跨 Agent 共享的用户偏好和稳定事实，对应 MemOS 的 `user_profile`
- **Agent Memory** 某个 Agent 的任务经验和协作约定，对应 `agent_{agentId}`

会话结束后，新增消息经过 LLM 判断和去重，从 Session 层沉淀到 User 或 Agent 层。这里有个反直觉的设计：**四层模型和 MemOS 的 text_mem/pref_mem/skill_mem/tool_mem 是两套分类维度**，不能一一对应——四层描述生命周期，MemOS 描述内容形态。

短期记忆工程化的核心是 **Redis 优先读取 + MySQL 兜底 + Token 窗口控制**。代码片段展示了关键的窗口裁剪逻辑：从最新消息向前累加 token，超过 `MAX_TOKEN_WINDOW_SIZE - SUMMARY_TOKEN_BUDGET` 就停止，并用会话摘要（2000 tokens 预算）补齐历史感。Redis 用 `leftPush` 写入最新消息在表头，超 200 条 `rightPop` 淘汰最旧。

长期记忆并行加载用 `CompletableFuture`，配专用线程池 `memoryLoadExecutor`（避免 ForkJoinPool.commonPool 争抢）。MemOS Search 的 query 拼装有意思：只把 `originalMessage` 作为主检索词，context 前 200 字符拼到 `userMessage` 后——也就是说**短期记忆不参与增强本次检索**，并行带来的是执行重叠，不是"短期已注入后再增强"。

**Token Budget 分配**是工程细节里的硬菜：长期记忆总预算 4000 tokens，user_profile 最多占 60%（2400 tokens），剩下的给 Agent 记忆。截断算法按行累加 token，达到预算停止——避免把单条记忆拆散。检索结果还要经过 `score < 0.3` 过滤和单条 1000 字符截断。

会话结束后写入流程用 Redis Set 记录已处理消息 hash 做去重，TTL 7 天；onSessionEndAsync 加 10 分钟会话锁。LLM 智能判断时把新增消息标记为 `[[NEW]]` 喂给模型，模型决定哪些值得长期保留。**本地去重**用四层相似度：exact → contains → 字符级 Jaccard（阈值 0.7）→ 短文本 Levenshtein（阈值 0.8）。**冲突处理**按 memCubeId 分组批量检测，再逐条决定写入新记忆、跳过、或记录待失效的旧记忆 ID。

最反常识的一段：**先写新记忆，后删旧记忆**。作者明说这是"写入优先"的风险控制，不是事务级一致性——MemOS 是外部 HTTP 服务，无法用本地事务同时包住新增和删除。删除失败只记 warning，新记忆继续保留。这等于把"不丢新数据"排在"及时清理旧数据"前面。

## 我的看法

我认同作者把"记忆分层"作为架构起点的判断，但有一个 push back：**四层架构的可推广性被 MemOS 的特殊性盖住了**。MemOS 在评测里胜出，但它是基于 cube 模型（user_profile / agent_{id} 这种可读可写命名空间），并不是所有长期记忆引擎都有这种结构。如果换成 Mem0（基于 entry 的扁平模型）或 LangChain 的 Zep 集成，四层架构的代码改动量并不小——你得自己实现 cube 等价物。这篇没讲"四层架构对底层引擎的依赖边界在哪"，导致它读起来更像 MemOS 落地文档，而不是可迁移的记忆系统设计。

第二个 push back：**best-effort 标注被过度使用**。文章至少三处说"Redis 失败时整段会话作为新增内容继续处理"、"hash 写入失败只记录日志"、"删除失败只记录 warning"。每一处单独看都合理，但合在一起意味着——**记忆系统没有强一致性保证，只有一堆局部降级路径**。实际跑生产时，问题不是"哪个组件失败"，而是"失败组合下记忆变成什么样"。作者没量化什么算"可接受失败率"，也没说失败监控告警怎么做，这是工程化最薄弱的一环。

第三个补充：**Token Budget 60% 给 user_profile 是经验值，不是设计选择**。如果你的 Agent 偏向工具调用（如代码助手），Agent 记忆的价值可能远高于用户画像（用户偏好变化慢，工具调用模式变化快）。文章没讨论如何按场景调权重，给的是个固定比例。一个更好的设计是让 budget 比例按 Agent 类型配置——客服 Agent 给 user_profile 多分配、研发 Agent 给 agent_{id} 多分配。

### 怎么落到 Agent 项目

如果让我基于这篇做一个**Agent 项目的记忆子系统**，我会画成这张图：

**核心模块五件套：短期缓存、长期引擎、LLM 判断器、本地去重器、冲突服务。**

1. **短期缓存**：MySQL + Redis 双写。Redis 用 List（最新消息在表头，超阈值 rightPop 淘汰）。写入顺序先 MySQL 再 Redis——MySQL 是持久化兜底，Redis 是热点缓存；Redis 失败不回滚 MySQL。这篇文章的代码片段可以直接抄，但 `MAX_CACHED_MESSAGES=200` 这种参数要按你的会话长度调。

2. **长期引擎**：选型不一定要 MemOS，Mem0 / Zep / 自己的 PG + pgvector 都能做。关键是提供两个 API：`search(scope, query) → List[Memory]` 和 `add(scope, content, importance)`。如果用 MemOS，注意四层模型与 MemOS 类型是两套维度——前者是生命周期，后者是内容形态。

3. **LLM 判断器**：会话结束后异步调用 LLM，决定哪些消息值得长期保留。Prompt 要包含完整对话上下文 + 标记新增消息（`[[NEW]]` 标记能让 LLM 知道重点看什么）。判断结果必须校验——LLM 偶尔会返回空或格式错。

4. **本地去重器**：同批次写入前先做内存级去重，按 exact → contains → Jaccard（0.7）→ Levenshtein（0.8）依次判断。这层只挡重复写入，跨历史的冲突留给冲突服务。

5. **冲突服务**：检测新增记忆和已有记忆是否冲突（语义相同但表述不同、事实矛盾等）。**先写后删**是新记忆优先——写入失败比删除失败危险得多。

**工程上最容易踩的坑：**
- 异步沉淀失败没有重试。文章用 Redis 锁 + hash 去重，但没说外部服务失败怎么补偿。建议在 onSessionEndAsync 里加 dead-letter 队列，失败任务落到 DLQ 用定时任务重试。
- Token Budget 截断按行累加——这能保留语义完整性，但对中文和多行内容不准。中文 token 估算偏长，多行 Markdown 经常被截掉开头。
- User Memory 和 Agent Memory 的权限边界——文章说"跨 Agent 共享"，但没说"哪些 Agent 能读哪些 cube"。如果两个 Agent 用同一个 userId，记忆就串了。

**面试时被问"Agent 怎么记住东西"**——直接答四层：Working（一步）、Session（一会话）、User（跨会话）、Agent（跨同 Agent）。**真正能上生产的不是这四层名字**，而是请求前并行加载、会话后异步沉淀、LLM 智能判断、本地去重、冲突处理、先写后删这一整套工程链路。讲名字是知识点，讲链路是工程能力。

## 一句话总结

Agent 记忆的难点不在分几层，而在每一层的写入时机、读取链路、一致性策略——把这五件事（并行加载、异步沉淀、LLM 判断、本地去重、冲突处理）做对了，记忆才从"塞 prompt"变成可工程化的子系统。