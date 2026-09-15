---
title: "日志平台 MCP + Claude Code Skill：自动化 BUG 排查 — 读《日志诊断 Skill》"
date: 2026-09-15
tags: [日志平台, MCP, Claude Code, Skill, BUG排查, 自动化诊断, SQL BUG]
summary: "得物技术（作者阿程）把日志查询 MCP 和 Claude Code Skill 结合，实现 /log-diagnosis 一行命令自动完成 查日志 → 找关键信息 → 扫描代码 → 定位根因 全流程。涵盖：MCP 鉴权（secretKey → accessToken，1 小时有效，最多同时 5 个）、Skill 执行链路（分页拉取最多 20 页日志 + traceId 第 9-16 位解析时间范围）、queryString 语法、实战案例 — 发现 SQL 字段 customer_tag 遗漏空字符串处理的隐蔽 BUG。"
source-url: "https://xie.infoq.cn/article/9ec163224ee6c0a2ecd387cc2"
source-title: "日志诊断 Skill：用 AI + MCP 一键解决BUG｜得物技术"
source-author: 得物技术
---

## 原文在说什么

得物技术（作者阿程）实战分享如何用 **日志平台 MCP + Claude Code Skill** 把 BUG 排查流程自动化。

**一、痛点与解决思路演进。** 后端调 BUG 固定流程：打开日志平台 → 搜 traceId → 找关键日志 → 复制类名方法名到 IDE 找对应代码 → 判断问题 → 不准再搜。**Q3 最初方案是 Cursor + MCP + 代码知识库**，但日志查询是"动态"的（依赖环境/应用/时间范围），无法静态预置。后来接触 Claude Code 的 Skill 概念（在项目里定义自定义命令，描述每个步骤），思路清晰了 — **日志平台有 MCP，Claude Code 有 Skill，两者结合 = 全自动 BUG 排查闭环**。

**二、日志平台 MCP 原理。** 基于 MCP（Model Context Protocol）协议的日志查询服务，让 Claude 直接调用日志平台能力。Claude Code 通过 **SSE（Server-Sent Events）长连接**与 MCP Server 通信，实时获取日志数据。

**三、鉴权流程。** `secretKey`（日志平台后管申请）→ `acquireTokenTool` → `accessToken`（1 小时有效，最多同时存在 5 个）→ 携带 accessToken 调用 `logsQuery / logSqlQuery / countLogTool`。

**四、/log-diagnosis Skill 工作原理。** Claude Code 支持通过 `.claude/skills/` 目录定义自定义技能，以 Markdown 文件描述行为规范。完整执行链路：
1. 用户输入 `/log-diagnosis {环境} {代码分支} {诉求}`
2. Claude 加载 `.claude/skills/log-diagnosis/SKILL.md`
3. 读取 `.diagnosis/config.json` 获取环境配置
4. 检查 accessToken 是否过期，过期自动刷新
5. **从 traceId 计算日志时间范围**（取第 9-16 位 16 进制时间戳）
6. **调用日志平台 MCP 分页拉取全量日志（最多 20 页，不遗漏）**
7. 切换到指定代码分支，结合日志关键词检索代码
8. 综合分析：上游日志 + 当前服务日志 + 代码逻辑 → 根因
9. 生成诊断报告（飞书文档 or 本地 Markdown）
10. 恢复原始代码分支

**五、queryString 语法。** `{field} {操作符} "{值}" {连接符} {field} {操作符} "{值}"`，操作符支持 `=` 精确匹配和 `≈` 模糊匹配（like），连接符支持 `AND / OR / NOT`。**时间范围只通过 start/end 参数控制，不要写在 queryString 中**。

**六、安装配置。** Claude Code 安装：`claude mcp add --transport sse dw-log-mcp-t1 https://{your-t1-aigw-domain}/api/v1/mcp/log-mcp/sse`（测试/预发/生产三套独立 MCP Server）。Skill 安装到 `.claude/skills/log-diagnosis/{SKILL.md, README.md, reference.md}`。`.diagnosis/config.json` 首次运行自动引导创建（唯一人工字段是 secretKey）。

**七、实战案例 — 隐蔽的 SQL BUG。** 某搜索接口 T1 环境无返回数据，拿到 traceId 执行：
```
/log-diagnosis T1 feature/your-branch trace_id: "your-trace" 为什么最终没有返回数据
```
AI 自动完成：(1) 提取请求入参；(2) 还原完整调用链路；(3) 识别关键节点 `resultList is empty`；(4) 提取 SQL 执行日志；(5) **AI 发现 SQL 中 customer_tag 只判断了 `IS NULL`，遗漏了空字符串 `''` 的情况**，其他字段都处理了 `IS NULL OR = '' OR FIND_IN_SET(...)`；(6) 定位到 MyBatis Mapper XML 中的问题代码，给出修复 `<if test="customerTag != null"> and (a.customer_tag IS NULL OR a.customer_tag = '' OR a.customer_tag = #{customerTag})</if>`。

**八、BUG 隐蔽性。** SQL 语法正确，逻辑上"看起来"没问题 — 只有对比其他字段的写法，才能发现 customer_tag 独自遗漏了空字符串处理。**这类细节差异，人工排查很容易忽略，AI 反而很擅长**（AI 没有先入为主的经验偏见）。

AI 给出的修复代码：
```xml
<!-- 修复后 -->
<if test="customerTag != null">
    and (a.customer_tag IS NULL OR a.customer_tag = '' OR a.customer_tag = #{customerTag})
</if>
```

**九、效率对比。** 传统人工排查需要"日志平台 ↔ IDE"来回切换至少 5-6 次，每次 5-10 分钟，总计 30-60 分钟；AI 自动化诊断只需一次 /log-diagnosis 调用，3-5 分钟给出根因 + 修复方案 + 报告，效率提升 6-10 倍。

## 我的看法

**我认同：** 文章最值得借鉴的不是 MCP 或 Skill 本身，而是 **"识别固定流程是自动化的起点"** 这个判断 — 凡是"步骤固定、信息来源明确、输出格式可预期"的工作，都值得用 Skill + MCP 自动化。BUG 排查、代码审查、性能分析报告生成、告警巡检都是典型场景。

**这篇文章给我最有价值的不是 X，而是 Y：** 不是 Skill 的目录结构或 MCP 安装命令，而是 **"分页拉取最多 20 页日志，不遗漏"** 这个工程细节。这种"反人性的强制约束"（人经常会偷懒只查第一页）恰恰是 AI 自动化的最大优势 — 把流程中的"反人性约束"用代码固化下来。

**反直觉的工程判断：**

1. **Skill 的本质是给 AI 写 SOP，不是训练模型。** 很多人误以为 Skill 是"教 AI 新知识"，但**Skill 文件是给 AI 的操作手册** — 写得越细、约束越明确（比如"禁止只查第一页就下结论""必须分页拉完所有数据"），AI 执行质量越稳定。这和人写文档本质上是一回事。

2. **AI 擅长"横向对比类" BUG 是反直觉的。** 大家以为 AI 擅长创造性问题，但本文案例揭示：**AI 在"同类字段逻辑不一致"这类问题上表现反而比人工更好** — 因为 AI 没有"先入为主"的经验偏见，会对所有字段做同等审查。这是 AI 落地的甜蜜区。

3. **traceId 里藏时间戳是日志平台设计的隐藏 API。** 文章说"取第 9-16 位 16 进制时间戳"反推日志时间范围 — 这意味着**traceId 设计时就考虑了反查能力**。这是个值得借鉴的设计模式 — 把"时间"编进 ID 里，比单独存时间字段 + 索引效率高。

**但我有 push back：**

1. **20 页日志拉取的 token 成本被忽视。** 每页日志可能上千条，20 页 × 1000 条 = 20000 条原始日志塞进 LLM 上下文。Claude 3.5 的 200K 上下文窗口虽然能容纳，但**单次诊断成本可能 $1-5**。文章没讨论日志预过滤（如只保留 ERROR/关键 trace）和摘要压缩。

2. **MCP 鉴权机制的并发安全没说清。** 文章说"accessToken 1 小时有效，最多同时存在 5 个" — 但**当 6 个并发会话同时跑 /log-diagnosis 时，token 池会怎样？排队？拒绝？自动扩容？** 这在生产多 Agent 并发诊断场景是个潜在阻塞点。

3. **诊断报告输出到"飞书文档 or 本地 Markdown"的隐私问题。** 当 traceId 涉及用户敏感数据（手机号/订单号），把日志原文写到飞书文档会扩散敏感信息。文章没讨论日志脱敏和审计。

### 怎么落到 Agent 项目

假设让我基于这篇做一个**"自动化 BUG 诊断平台"**，会拆成五个模块：

1. **MCP 协议适配层**：封装日志平台 MCP 接口，支持多环境（测试/预发/生产/海外）+ 多租户 token 管理池（LRU 缓存，自动刷新）。
2. **Skill 模板引擎**：用 Markdown + Jinja2 模板描述诊断 SOP，支持"分页拉取 + 强制全量 + 反人性约束"等参数化配置。
3. **日志预过滤器**：在 token 灌入 LLM 前做 ERROR/WARN 过滤 + 关键 trace 字段提取 + PII 脱敏，控制单次诊断成本。
4. **多源关联引擎**：把日志 + 代码（Git 分支切换）+ Trace（APM 调用链）+ 监控（Metrics）四源数据按 traceId 关联，构建完整诊断图谱。
5. **诊断报告中心**：把每次诊断结果归档（类似 OpenSpec 的 archive 机制），下次同类 BUG 直接复用历史结论。

**面试回答脚本：**"BUG 排查自动化靠的不是更聪明的 AI，是**把固定流程 + 反人性约束用 Skill 写死**。我在做的诊断平台，核心是 MCP 多租户适配 + 日志预过滤降本 + 多源关联根因，把 30 分钟的人工排查压到 5 分钟，且每个诊断都自动沉淀到知识库。"

**与得物方案的延伸对照：** 得物的 /log-diagnosis 是单 Agent 闭环方案。**企业级演进路径应该走"多 Agent 协同诊断"** — 一个 Agent 负责日志采集、一个负责代码定位、一个负责依赖分析（拉 APM/SkyWalking 数据）、一个负责修复方案验证。这样每个 Agent 上下文更小、调试更精准，但也带来 Agent 间协议设计的新复杂度。

## 一句话总结

BUG 排查自动化的本质是 **"MCP 接入数据 + Skill 写入 SOP"** — 用 MCP 给 AI 装上"查日志的眼睛"，用 Skill 给 AI 写一份"禁止偷懒的操作手册"；两者缺一不可，否则 AI 拿到数据但不会系统分析，或有流程但没数据来源。