---
title: LangChain 自己的 Paid Media Agent：把 Agent 当新员工，给电脑、配任务、用代码代替推理
date: 2026-09-15
tags: [Agent, LangChain, Deep Agents, 工程实践]
summary: LangChain 内部 6 个月把付费投放占比从 0 拉到 20%，CPL 降 30%，分析报告从 18 分钟 / $3 降到 85 秒 / 1/40 成本。核心思想：把 Agent 当知识工作者——给沙箱 + 软件 + 业务 wiki；用代码做确定性计算，让模型只做判断；子 Agent 隔离 context 但隔离不止是 context。
source-url: https://www.langchain.com/blog/paid-media-agent
source-title: How we built LangChain's Paid Media Agent
source-author: Amal Irgashev / Danny Lambert / Jan Gomez
---

## 引子

LangChain 自家 6 个月把付费媒体从 0 做到贡献 20% pipeline，CPL 降 30%，每月节省 $5K agency 费。更关键的是把一个早期"每周分析报告"Agent 从 18 分钟 / $3 优化到 **85 秒 / 1/40 成本**。这篇文章不讲 prompt 技巧，讲的是**怎么搭一个 Agent 的工作环境**——以及踩过的 5 个工程坑。

面试讲 Agent 项目的时候，这篇文章给的 5 条工程原则都是可直接借用的。

---

## 一、核心思想：把 Agent 当知识工作者来"招"

> "A coding agent is a knowledge worker. Knowledge work often involves reading files, transforming information, running analyses, and writing things down."

LangChain 没有把 Agent 当成"一个 LLM + 一堆 tool call"。他们把它当**新入职的付费投放分析师**，给它：

- **一台电脑**（LangSmith Sandbox，32 GB disk microVM）
- **软件**（pandas / DuckDB / openpyxl / WeasyPrint / Jinja2）
- **数据访问**（BigQuery + 各广告平台 MCP）
- **业务知识**（19 页 wiki + 6 个 skills）
- **工作说明**（system prompt 是地图，不是课本）

**LangSmith Sandbox 镜像打包**：把软件和 wiki 烤进 sandbox snapshot，启动省 10 秒。这是个被低估的工程细节——**冷启动延迟是 Agent 体验的隐形杀手**。

**工程落地 checklist**：
- ☐ 给 Agent 一个独立的 microVM（不是本地进程），每个 session 一个独立 sandbox
- ☐ 把常用软件 + 业务文档烤进 base image，session 启动只挂载会话级数据
- ☐ **system prompt 是导航图，不是百科全书**——把所有上下文硬塞进 system prompt 会让 prompt 越来越长、越来越旧、越来越贵

---

## 二、5 层上下文分层：核心架构抽象

这是这篇文章工程价值最高的部分。LangChain 把 Agent 的 context 拆成 5 层，**按"变化速度"排序**：

| 层级 | 变化频率 | 作用 | 加载方式 |
|---|---|---|---|
| System prompt | 几乎不变 | 角色 + 导航 + 数据来源说明 | 每次必带 |
| Skills | 偶尔变 | "怎么做工作"（6 个目录） | **渐进披露**——只看 title + description |
| Wiki | 偶尔变 | "业务是什么"（19 页） | 按需 RAG / 文件读取 |
| Live tools | 每天变 | 花费、设置、pipeline | 调用时实时取 |
| Deterministic code | 不变 | 计算、规则、安全护栏 | 强制在代码里 |

**Skills vs Wiki 的判定线**（这一条非常值得在面试里讲）：

> "**A skill should 'work at another company', whereas the wiki should not.**"

- **Skill** = 跨公司可复用的工作方法（"怎么读广告数据""怎么跑 WoW 对比""怎么写报告"）
- **Wiki** = 仅 LangChain 适用的业务知识（"哪个 campaign 是 awareness 用途""7 月我们为什么这么决定"）

**这跟 Karpathy 的 LLM wiki、LangChain 自己的 Wiki Memory skill 是同一个模式**。**好的 context 设计是把"通用方法"和"特定业务"解耦**——否则你每次业务变更就要重写整个 system prompt。

**工程落地 checklist**：
- ☐ 把 prompt 拆成"导航 + skills 索引 + wiki 索引"三段，而不是把所有知识塞一段
- ☐ Skills 用渐进披露（先只暴露 title + description，按需加载完整指令）
- ☐ Wiki 用 RAG 或文件系统按需检索，**不**进 system prompt
- ☐ 计算/规则/安全护栏 100% 在代码里（"禁止在 pipeline top driver 一周差就砍掉"这类规则不能让模型判断）

---

## 三、用代码做确定性，用模型做判断——核心性能优化

LangChain 的早期版本让模型算 spend、算 WoW 变化、分类 campaign 表现。结果：

- **3.9M input tokens / 次**（模型读所有原始数据再算）
- **1,112 秒 / $3+ / 次**
- 每个 run 数字都重新算，**结果难复现**

优化后：
- **Python 算**所有确定性的事（拉数、对齐时间窗、求和、做对比、应用规则）
- **模型只解读**：为什么这个 campaign 表现变了、下一步该做什么
- 结果：**85 秒 / 1/40 成本**

**这是 Agent 工程的通用原则**：**确定性逻辑用代码、概率性逻辑用模型**。模型做"为什么 / 该做什么"，代码做"是多少 / 该怎么做"。

**面试可讲角度**：这是 *build vs buy* 的工程化版本——**模型是"判断库"，代码是"执行库"，两者通过清晰的 boundary 通信**。任何工程上能用代码锁死的，都不要让模型推理。

**工程落地 checklist**：
- ☐ 区分清楚**计算**（代码）和**判断**（模型）的边界
- ☐ 重复的 ETL / 对齐 / 求和一律脚本化
- ☐ 任何"硬规则"（风控、合规底线）编码化，**不让模型覆盖**
- ☐ 模型输出"建议"，代码输出"动作"——动作链路完全确定

---

## 四、Subagent 隔离：context 之外还要设计

LangChain 测了 3 种 5 平台并行的架构：

| 架构 | 优点 | 缺点 |
|---|---|---|
| 每个平台独立 run | 最简单 | 多 Slack 消息、跨平台合成差 |
| 单 Agent 处理所有 | 跨平台合成好 | context 爆 |
| **Parent + subagents per platform** | 父 context 小 + 子 context 独立 | **隔离要自己设计** |

他们最终选了第三种，但**踩了 3 个坑**——这三个坑每个 Agent 项目都会遇到：

1. **平台间互相压制**：两个 subagent 写报告到同一路径、共享同一"done"标志，第一个完成后第二个以为是自己完成的就停了。修：**每个 subagent 独立 report location + completion state**。
2. **Subagent 死循环自验证**：一个 subagent 不知道怎么判断 PDF 生成成功，反复检查文件、烧 token，最后想自己重写 PDF。修：**subagent 只给 3 个 tool：read context、compute、render**，render 成功 = 完成。
3. **Context 隔离 ≠ 全隔离**：subagent 给你的是独立 context window，**但其他隔离（工具、文件、状态、返回值、失败处理）要自己设计**。

**面试可讲角度**：这是 *process isolation* 在 Agent 时代的版本。**传统微服务的隔离是 network namespace + cgroup，Agent 的隔离是 context window + 工具白名单 + 文件沙箱 + 状态命名空间**。**context 隔离只是最浅一层**。

**工程落地 checklist**：
- ☐ 每个 subagent 独立的工作目录（`/sandbox/<subagent_id>/...`）
- ☐ 每个 subagent 独立的"完成状态"——不要共享 flag
- ☐ **subagent 只给最少 tool**（3-5 个 max），其他一律不可见
- ☐ Subagent 的"完成"判定 = 输出文件落盘 + 调用 `task_done` tool，不要让它自我验证
- ☐ Parent 拿到的只是结构化 summary，**不**是 subagent 的中间过程

---

## 五、从分析到行动：Agent 工程的"最后一公里"

光做分析的 Agent 是个更好的 dashboard。LangChain 的设计：

- Agent 在 Slack 里**直接提案**（加关键词、改地理定向、新建 search campaign）
- **权限**通过 Slack user ID 校验——非授权人连提案都看不到，只看到 blocking
- 提案以 **Slack Block Kit approval card** 呈现：当前值 vs 提议值并列
- **人工 approve 后代码执行**，并**回查广告平台确认动作成功**

这条链路解决了"分析 ≠ 行动"的鸿沟。**Agent 的工程价值不在它想得多准，而在它能让团队更快地闭环**。

**面试可讲角度**：这是 *human-in-the-loop* 的工程化。**不要让 Agent 直接调用 mutating tool；走 approval → verify 链路，把"决策权"和"执行权"分开**。

**工程落地 checklist**：
- ☐ Mutating tool 必须经 approval gate，**不要**让 Agent 直连生产写 API
- ☐ Approval UI 要显示 diff（当前 vs 提议），让人 5 秒判断
- ☐ 执行后必须 verify（再调一次 read API 确认状态变了）
- ☐ 权限校验放在服务端，**不要**写在 prompt 里

---

## 六、简历可直接借用的项目骨架

如果你的简历要写一个 Agent 项目（比如"为某业务搭建的投放 / 客服 / 运营 Agent"），可以参考 LangChain 的这个骨架来组织项目描述：

```
项目名：[业务名] AI 助手 / Agent 平台

架构（按 5 层 context + parent/subagent 描述）：
- 入口：[Slack / Web / API]
- 父 Agent：[Deep Agents / LangGraph] 编排
- 子 Agent：[N 个] 按 domain 隔离，每个独立 sandbox + 独立工具集
- 工具层：[MCP server / internal API]
- 数据层：[BigQuery / vector store / knowledge graph]

关键工程决策（5 条，每条一句话）：
1. 上下文分层：prompt 是导航图，skills/wiki 按需加载
2. 确定性用代码：所有计算/规则写在 Python 里，模型只做判断
3. Subagent 隔离：context window + 文件路径 + 工具白名单三层
4. Tool discovery：tool catalog 按需 search，不全量加载（200+ tool 起步 38K token → 12K token）
5. Human-in-the-loop：所有 mutating 操作走 approval card → 代码执行 → 平台 verify

成果（量化）：
- 性能：单次任务 [N] 分钟 → [M] 秒，成本 [X] → [Y]
- 准确率：[A]% 任务一次性完成
- 业务：[B] 项 mutating 操作已通过 Agent 闭环
```

**面试常被问到的延伸问题**：
- "为什么不让模型算 spend？" → 模型做计算的代价、不可复现性、token 浪费
- "subagent 之间怎么通信？" → **不直接通信，走共享文件系统 + structured summary**
- "tool 太多怎么办？" → MCP catalog + search tool + read schema + execute 三段式，按需加载
- "怎么防止 Agent 误操作？" → 工具白名单 + Slack user ID 鉴权 + approval gate + execute 后 verify
- "怎么评估？" → frozen test set + 真实复现的周报数字对比 + agent 完成率

---

## 配套阅读

- **同主题更通用**：[3 Years of Graph Engineering with LangGraph](blog/posts/2026-09-15-langgraph-three-years-patterns.md) — graph vs harness vs loop 的判别标准
- **架构抽象**：[Building monday.com Sidekick](blog/posts/2026-09-15-agent-sidekick-bounded-responsibilities.md) — 单 Agent 失败 → 多层架构的另一案例
- **底层基建**：[Claude Agent SDK](blog/posts/2026-09-15-claude-agent-sdk-engineering.md) — sandbox + hook + subagent 的 SDK 实现

参考资料：

- [How we built LangChain's Paid Media Agent](https://www.langchain.com/blog/paid-media-agent) — Amal Irgashev, Danny Lambert, Jan Gomez
- [Open-sourced Paid Media Agent](https://github.com/langchain-ai/open-paid-media-agent)
- [LangSmith Sandbox](https://docs.langchain.com/langsmith/sandboxes)
- [Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview)
