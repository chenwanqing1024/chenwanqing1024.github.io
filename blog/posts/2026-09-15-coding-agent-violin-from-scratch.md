---
title: Coding Agent 不复杂：拆开看就是 while 循环加三层分离
date: 2026-09-15
tags: [Coding Agent, 架构设计, 多协议适配, 工程落地]
summary: 得物 Violin 这篇把 Coding Agent 拆给你看——三层架构（模型适配 / agent-core / 产品层）、EventBus 驱动、Agent Loop 一个 while 循环搞定。核心是它把"AI Coding Agent"这个看似高深的东西还原成一个标准的、可工程化的客户端-服务端架构。会这个套路，你也能写一个 Claude Code。
source-url: https://xie.infoq.cn/article/d63d2c29ab0c137fad2f12958
source-title: 实战从零开始构建一个Coding Agent：Violin｜得物技术
source-author: 得物技术
---

## 原文在说什么

得物这篇是工程味最重的一篇——从零写一个叫 Violin 的 Coding Agent。作者的判断很直接：客服、数据分析、工作流编排这些业务 Agent 追根溯源都是 Coding Agent 的泛化变种，**理解了 Coding Agent 的构建原理，就掌握了理解其他 Agent 的一把钥匙**。

Violin 架构深度借鉴了 Pi（一个 TypeScript 实现的 AI Coding Agent）的三层分离：**模型适配层 / 内核层 / 产品层**，配合 EventBus 事件驱动、工具注册表和插件系统，每个模块各司其职且松耦合。Pi 是公开项目，作者强烈推荐学习（how-pi-agent-works）。

语言选择很有意思——引擎用 Zig（追求极致性能和内存可控），Client 端用 Python（利用 Python 生态快速搭终端 UI），**通过 TCP + JSON line 协议通信**。这印证了一个工程原则：每层通过接口或网络协议解耦后，不同层可以用不同语言实现，不需要也不可能"全部用一种语言写完"。

**第一层：模型适配层（ai）。** 不同模型 API 对工具调用、推理内容、缓存、错误、OAuth、流式协议的表达都不同。Violin 把这些差异统一成 `Message`、`Tool`、`AssistantMessageEvent` 和 `streamSimple()`。这样上层 Agent Loop 不需要知道"这是 Anthropic 的 tool_use 还是 OpenAI Responses 的 function call"，只关心统一后的 `toolCall` 内容块。OpenAIAdapter 和 AnthropicAdapter 代码量差不多（531 vs 558 行），差异主要在请求体格式、工具调用结构、流式协议三处。

**第二层：agent-core。** Agent Loop 是一个 while 循环，在"问模型"和"执行工具"之间切换，直到模型给出最终答案。简化后的核心代码：

```zig
while (turn < max_turns) : (turn += 1) {
   // 1. 调模型
   const assistant = try model.complete(.{
       .messages = messages.items,
       .tools = tool_registry.definitions(),
   });

   // 2. 检查是否有工具调用
   const has_tool_calls = assistant.toolCalls().len > 0;

   // 3. 没有 → 结束；有 → 逐个执行工具
   if (!has_tool_calls) break;
   for (assistant.content) |block| {
       if (block == .tool_call) {
           const result = tool_registry.execute(tc.name, tc.args);
           messages.append(result);
       }
   }
}
```

Agent Loop 只关心"循环"，不关心消息从哪里来、执行结果存到哪里。这些"循环之外的事"——会话历史的加载和保存、上下文压缩后的重试、Arena 内存管理——由产品层封装。

**第三层：产品层（product）。** 把 Agent 变成每天能用的开发工具，做这些"麻烦但关键"的事情：会话历史持久化、上下文压缩、SKILL/AGENTS 加载、UI 渲染。

`agent.zig` 只有 123 行，但是把整个项目粘起来的那层。它做三件事：① 加载历史 ② 调 loop.run() ③ 处理 ContextOverflow 时压缩重试。Session 是 JSONL 存储，每行一个独立 JSON 对象，第一行是会话头（id/created_at/cwd），后续每行是一条消息。SessionStore 用 parent_id 维护树形结构，**支持 fork 和回滚**——这是 Pi 的设计，Violin 继承了。

**Compaction** 是 Coding Agent 长期可用性的关键。LLM 有上下文窗口限制，对话可能持续几十轮累积数千 token。Violin 的解法：字符数/4 估算 token（不引入 tokenizer，够用就行），超过 100K token 阈值时把旧消息压缩成摘要，保留最近 10 条消息、摘要目标长度 500 token。压缩系统分两层——**Loop-level（单次循环内）和 Session-level（跨循环）**。

**Resources** 从文件系统加载 AGENTS.md / CLAUDE.md / SKILL.md，解析 frontmatter 格式化为 system prompt 注入 LLM。优先级明确：项目级规则先，全局规则兜底；同名冲突时项目赢。这跟 Claude Code 的设计一致。

## 我的看法

我认同作者把 Coding Agent 拆成"模型适配 + 内核循环 + 产品层"三层的判断。这是教科书式的分层架构——任何一个 LLM 应用本质都是这三层。但这篇文章给我最有价值的不是分层本身，而是几个反直觉的工程细节：

第一，**Agent Loop 真的就是一个 while 循环**。核心代码 30 行不到。所有看起来"很 AI"的复杂行为——多轮推理、工具调用、自我反思、Plan 模式——展开到底层都是这个 while 循环在跑。这跟写一个编译器很像：表面上有 lexer/parser/typecheck/codegen 这么多阶段，本质就是一个状态机在状态之间迁移。

第二，**用 TCP + JSON line 做客户端-服务端通信**。这个选择背后是"语言无关"的设计哲学——引擎用 Zig 追求性能、Client 用 Python 追求生态，两层之间用最朴素的协议通信。这跟微服务架构里"用 HTTP/RPC 解耦服务"的思路一模一样。**任何 LLM 应用都该考虑这种分层**，否则你会被"用一种语言写到底"绑死。

第三，**字符数/4 估算 token**。不引入 tokenizer 是非常聪明的工程取舍——tokenizer 加载慢、内存占用大、还有 BPE 版本兼容问题。但字符数/4 只对英文文本准确，对中文（每个汉字 ≈ 1.5 token）会低估 50%。如果你的 Agent 处理中文内容，要按字符数/1.5 或者字符数/2 来估算。

但我有几个 push back：

第一，**ContextOverflow 时的重试策略没说清**。文章说"agent.zig 调用 loop.run() 时传入历史消息，loop 返回后它负责把新消息持久化到 Session，并在 ContextOverflow 时截断上下文重试"。但 "压缩后重试"是不是应该把 loop 的中间状态也清理？会不会出现压缩完但 loop 还在跑的情况？这是状态机一致性的经典问题。

第二，**Tool 注册表的设计**。文章给的伪代码很简洁——HashMap 存工具，按 name 查找。但实际工程里有几个问题没解决：① 工具的权限边界（用户只能调读工具不能调写工具）② 工具的超时和取消 ③ 工具执行的审计日志。**生产级 Agent 的 Tool Registry 不是 HashMap，是带 ACL 的执行沙箱**。

第三，**Compaction 的 100K token 阈值是经验值**。文章没说这个值怎么调——按什么模型调（GPT-4o 128K、Claude 200K、Sonnet 1M）？如果同一个 Agent 跑在不同模型上，阈值要不要动态调整？

### 怎么落到 Agent 项目

如果让我基于这篇做一个**通用 Agent 框架**，我会画成这样：

**核心模块三件套：Model Adapter、Agent Loop、Product Layer。**

1. **Model Adapter**：定义统一接口（`complete`、`stream`），每个 Provider 实现一份。差异最大的三处：请求体格式、工具调用结构、流式协议。**不要试图用 JSON Schema 完全抹平差异**——OpenAI 和 Anthropic 的 tool_call 字段命名不同，硬抹平反而要写一堆 if-else。

2. **Agent Loop**：while 循环 + max_turns 上限 + 工具执行 + 错误分类（可重试 vs 不可重试）。**错误分类是生产级的关键**——网络抖动可重试、参数错误不可重试、配额超限要退避。Loop 只关心"循环"，其他都是上层的事。

3. **Product Layer**：胶水层，负责会话持久化、ContextOverflow 压缩重试、资源加载、UI 渲染。**这一层代码量不大但价值最高**——把 Loop 包成可用的产品。

**工程上最值得做的：**

- **JSONL + 树形结构存 Session**：parent_id 支持 fork 和回滚，比线性追加灵活得多
- **TCP + JSON line 做客户端-服务端**：跨语言、跨平台、调试方便（用 tcpdump 都能看）
- **压缩分两层**：Loop-level 压缩单次循环，Session-level 压缩历史，对应不同优先级

**面试时被问"自己实现一个 Coding Agent 怎么做"**——直接答三层：模型适配层（统一 API 差异）、agent-core（while 循环 + 工具注册）、产品层（会话 + 压缩 + 资源）。**真正的工程能力不在分层本身**，而在于：错误分类、重试策略、压缩策略、Tool 沙箱、资源加载优先级——把这五件事做出来，Agent 才从 demo 变成产品。

## 一句话总结

Coding Agent 不复杂——它是三层分离（适配/内核/产品）加一个 while 循环；复杂的是 while 循环之外的事：错误怎么分类、上下文怎么压缩、Tool 怎么隔离、会话怎么持久化——这些才是从 demo 到产品的距离。