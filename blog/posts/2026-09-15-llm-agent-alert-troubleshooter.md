---
title: 告警排查 Agent 不是替代运维：把 20 分钟的拼凑工作压到 4 分钟
date: 2026-09-15
tags: [LLM Agent, 告警排查, ReAct, 工程落地]
summary: 这篇不讲"AI 排查告警"，讲怎么用 ReAct Agent 把"打开三个平台拼凑数据"这种 20 分钟的体力活压到 4 分钟。核心是 SupervisorAgent + 四个 @Tool（queryLogs / queryMetrics / queryTrace / queryEndpointErrors）+ 工具超时隔离 + 幻觉控制四道闸。结论验收 Agent + 多轮交叉验证才是让 AI 排查能上生产的工程关键。
source-url: https://xie.infoq.cn/article/d45338880b32d1a60b8c83512
source-title: 用 LLM Agent 重构告警排查流程｜得物技术
source-author: 得物技术
---

## 原文在说什么

得物这篇讲的是告警排查的工程现实——告警来了，第一反应是打开日志平台搜关键词、切 APM 看监控曲线、去链路追踪系统找 trace 详情，三个平台来回切换，最后发现只是上游 GC 抖动导致的瞬间超时。这类告警排查通常需要 10-30 分钟，主要耗时不在分析本身，而在频繁登录不同平台、拼凑分散数据。

Troubleshooter 是得物做的 LLM 排查 Agent，中位数排查耗时从 20 分钟降到 4.4 分钟，覆盖 11 个服务和 10+ 种告警类型。

架构核心是**告警接入与排查执行解耦**——接入层只负责接收和持久化，排查由独立调度器异步触发。Agent 框架选 Spring AI Alibaba 而不是自建 ReAct 循环，主要是省事——框架已内置推理循环、工具拦截器、模型拦截器。

SupervisorAgent 的核心设计不是"调大模型"，而是**四个 @Tool 方法**：

```
@Tool queryLogs       — 按优先级查询日志（traceId > exceptionName > endpoint > keywords）
@Tool queryMetrics     — 查 10 维度（QPS/RT/错误率/CPU/内存/GC/百分位RT/Top10）
@Tool queryTrace       — 查分布式调用链 Span 树
@Tool queryEndpointErrors — 无 traceId 时按接口路径查错误日志，正则提取 traceId
```

执行逻辑：动态构建 instruction（策略匹配 + 兜底策略）→ 构建 ReactAgent → **最多 2 次 LLM 内容重试 + 1 次验收**。

四个工具的工程细节非常具体：

- `queryLogs` 按 traceId > exceptionName > endpoint > keywords 优先级分批查询，**LogDeduplicator 防同一请求的多条日志重复占据分析窗口**
- `queryMetrics` 支持 10 个维度，LLM 根据告警类型自主决定查哪些维度——OOM 查 GC+内存+CPU 全维度，接口 RT 突增查 QPS+RT+百分位
- `queryTrace` 把 Span 树渲染为格式化文本给 LLM
- `queryEndpointErrors` 有防护逻辑：endpoint 为根路径 "/" 时**直接拒绝执行**（匹配所有请求的查询不具备排查意义）

**动态策略组装**：按 `(service_name, alert_type)` 从数据库精确匹配排查策略，未匹配时用内置兜底策略。运维人员可**通过前端页在线编辑策略内容，无需改代码**——这把策略的所有权和迭代权交到运维手里。

**工具超时隔离**用 `ToolExecutor` 包装，Future.get(timeout) + 独立线程池。超时时返回降级消息（"指标查询超时，继续使用已有信息"），**LLM 基于已有证据继续推进，不因单工具超时导致整个排查中断**。

幻觉控制是这篇文章的工程灵魂，分四道闸：

1. **规则格式校验**（零 LLM 调用）：毫秒级检查 5 个必要章节和指标表格格式
2. **独立验收 Agent**：检查结论明确性、核心判定合理性、根因证据链、建议可执行性
3. **多轮交叉验证**：queryLogs 与 queryTrace 交叉、queryLogs 与 queryMetrics 交叉、时间线一致性校验
4. **重试机制**：格式问题不消耗重试配额；内容问题最多 2 次；验收 Agent 异常时宽容通过

排查可观测性：每次排查在文件系统创建独立目录（按事件 ID），LoggerInterceptor + ToolInterceptor 记录所有 LLM 输入输出和工具调用返回——**让运维能看到 AI 每一步在做什么**。

## 我的看法

我认同作者把"四个 @Tool + SupervisorAgent + 验收 Agent"作为告警排查 Agent 架构起点的判断。但这篇文章给我最有价值的不是架构本身，而是几个反直觉的工程判断：

第一，**LLM 排查不等于构造 prompt 丢给大模型**。很多人误以为"AI 排查"= prompt engineering，实际是 LLM **无法凭空知道你的服务当前 QPS、错误日志、调用链**。没有工具的 LLM 排查就是闭眼开车。这跟 #17 的"通用 Agent + 业务 Skill"是同一个范式——业务能力封装在工具里，LLM 只负责推理。

第二，**工具超时隔离是单点故障的对冲**。日志平台、APM 不一定稳定，一个工具超时整个流程就崩，是最差的设计。文章用 `Future.get(timeout)` + 降级消息，让 LLM 在已有证据上推进，这是分布式系统设计里**部分失败 (partial failure) 处理**的经典套路——LLM 排查流程跟微服务调用链是一回事。

第三，**幻觉控制要分层**。纯靠 prompt 防幻觉是死路。文章给的四道闸——格式校验、验收 Agent、交叉验证、重试机制——其实是软件测试的"单元测试 + 集成测试 + 系统测试 + 重试"映射到 LLM 场景。**LLM 输出不稳定是落地最大风险，必须用软件工程方法对冲**。

但我有 push back：

第一，**"中位数 20 分钟降到 4.4 分钟"** 这个数字要谨慎看——告警排查的中位数受告警类型分布影响很大。如果你的告警大多是 GC 抖动、网络抖动这种"自愈型"告警，AI 排查的提速最明显；如果是复杂的内存泄漏、依赖冲突，AI 提速有限。文章没拆告警类型分布。

第二，**多轮交叉验证的边界没说**。交叉验证是查询耗时翻倍——`queryLogs` 和 `queryTrace` 交叉要查两次。文章没说交叉验证的触发条件，是无条件交叉还是有可疑结论才交叉？前者成本高，后者容易漏。

第三，**策略数据库在线编辑**是好设计但没版本控制。运维改了策略后想回滚怎么办？没有 git 化的策略管理，编辑次数多了就成了"屎山"——比代码屎山更难治理。

### 怎么落到 Agent 项目

核心模块五件套：**Supervisor Agent + Tool 注册中心 + 验收 Agent + 策略数据库 + 可观测文件系统**。

1. **Supervisor Agent**：Spring AI Alibaba / LangGraph / LlamaIndex 都行，关键是**工具调用 + 验收循环 + 重试机制**。
2. **Tool 注册中心**：每个工具一个 @Tool 方法，统一封装超时、降级、日志。**关键反模式：让 LLM 直接看到所有平台原生 API**——应该包一层领域语义。
3. **验收 Agent**：独立 LLM 评估结论的合理性，比主 LLM 更便宜、更快、约束更强。
4. **策略数据库**：`(service_name, alert_type)` → 排查策略，**支持在线编辑 + git 版本化**。
5. **可观测文件系统**：每次排查一个独立目录，记录 LLM 输入/输出和工具调用——让运维能"复盘 AI 决策"。

**面试时被问"LLM 怎么落地到运维场景"**——直接答"四个 Tool + 验收 Agent + 工具超时 + 交叉验证"。**真正的工程能力不在架构本身**，而在于：工具超时降级、验收 Agent 设计、幻觉控制分层、策略可治理——把这四件事做出来，LLM 才从"会说话的 demo"变成"能用的工具"。

## 一句话总结

告警排查 Agent 的核心不是 LLM 多强，而是工具的领域封装、超时降级、验收 Agent、交叉验证——LLM 推理只是中间环节，真正决定能不能上生产的是这套工程护栏。