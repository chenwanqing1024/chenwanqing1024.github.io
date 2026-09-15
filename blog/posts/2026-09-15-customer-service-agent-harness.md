---
title: 智能客服 Agent：从 Single-Agent 到 Harness 架构 + 数据飞轮
date: 2026-09-15
tags: [智能客服, Multi-Agent, Harness, DPO, 工程落地]
summary: 这篇不讲"AI 客服"，讲智能客服 Agent 怎么从 Single-Agent → Multi-Agent → Harness 架构演进，以及 PE 自动化 + DPO 训练数据飞轮。核心是 Harness 把跨场景复用做出来，PE 自动化流水线让 Prompt 持续优化，DPO 训练让模型学会"正确决策"。
source-url: https://xie.infoq.cn/article/a93ce781167688a3b61d5364e
source-title: 从"机械应答"到"服务伙伴"：得物高可控智能客服的 Agent 工程实践｜AICon 演讲整理
source-author: 得物技术
---

## 原文在说什么

得物这篇讲智能客服 Agent 的架构演进。传统结构（意图分类 + NER + 对话管理 + FAQ 召回 + 重排的流水线）有四个上限：① 无法处理多步骤任务 ② SOP 人工维护成本高 ③ 多模型运维成本高 ④ 会话拟人度不够。

Agent 智能客服的挑战：场景复杂长尾 case 的 PE 优化成本高、长 Context 多轮能力不足、对齐人工拟人化不足、多轮半双工下消息控制困难。

**架构演进三阶段**：

**第一阶段：Single-Agent（单 Prompt）**——基于 Qwen，问题明显：单一 Prompt 难以覆盖多场景。

**第二阶段：Multi-Agent（渐进式披露）**——采用 AutoGen 的 Multi-Agent 架构，通过 `SelectorGroupChat` 模式实现动态调度，**解决率提升明显**。

**跨场景 Harness 架构**——为解决跨场景复用问题，进一步演进至 Harness 架构，核心能力包括场景配置、Skill 复用、统一调度。

**数据飞轮 = PE 自动化 + 模型训练**。

**PE 自动化流水线**：人工 Prompt Engineering 痛点是时间成本高、多 case 引发 Prompt 冲突与歧义、Token 成本和指令遵循能力有限。流水线流程：① 对比数据抽取（LLM 抽取转人工 case 中 Agent 回复 Bad 和人工回复 Good） ② PE 修改建议（LLM 分析 Prompt 修改建议） ③ 人工 Review 标注可行性 ④ 离线跑测 ⑤ 上线实验积累数据。

**DPO 模型训练飞轮**——通过 LLM-as-a-Judge 搜集回流数据并重新训练，让模型学会"正确决策"。

## 我的看法

我认同作者把"Single → Multi → Harness"作为客服 Agent 架构演进路径的判断。这篇文章给我最有价值的不是架构本身，而是几个工程判断：

第一，**架构演进反映业务复杂度**。从 Single-Agent 到 Multi-Agent 是因为单 Prompt 装不下多场景；从 Multi-Agent 到 Harness 是因为多智能体之间的复用不够。**架构不是设计出来的，是被业务逼出来的**——这是很健康的演进。

第二，**PE 自动化流水线比 Prompt Engineering 本身更重要**。人工调 prompt 是时间黑洞且容易冲突，**流水线化**让"调 prompt"变成"LLM 提建议 + 人工 Review + 离线跑测 + 上线实验"的工程化流程。这跟传统软件开发的"代码 review + CI/CD + 灰度发布"是同一个范式。

第三，**DPO 训练数据飞轮是让客服 Agent 学会业务的根本路径**。LLM-as-a-Judge + 人类反馈 + 持续训练，让模型从"会说话"变成"会做客服"——这不是 prompt 能解决的，必须训练。

但我有 push back：

第一，**Harness 架构的具体设计没说**。Harness 跟 #22 的 Instinct 系统、#4 的 EP-Harness、#18 的多仓管理 Harness 是不是一回事？得物内部有没有统一的 Harness 抽象？还是每个场景单独设计？这关系到架构的可复用性。

第二，**LLM-as-a-Judge 的偏差问题**。用 LLM 当裁判评估另一个 LLM 的回复——这种"自己评自己"的方法有循环偏差。文章没说怎么避免。

第三，**DPO 训练的成本与效果没说**。客服场景的 DPO 训练数据规模、训练频率、效果指标——这些是工业落地最关心的数字。

### 怎么落到 Agent 项目

核心模块五件套：**Harness 平台、PE 自动化流水线、LLM-as-a-Judge 评估器、DPO 训练飞轮、A/B 实验框架**。

1. **Harness 平台**：跨场景复用——统一调度 + 场景配置 + Skill 复用
2. **PE 自动化流水线**：LLM 提建议 + 人工 Review + 离线跑测 + 灰度发布
3. **LLM-as-a-Judge 评估器**：评估 Agent 回复质量，作为训练数据源
4. **DPO 训练飞轮**：用人工 + 评估反馈持续训练模型
5. **A/B 实验框架**：新旧 Prompt/模型对比，决定上线与否

**面试时被问"AI 怎么落地到客服场景"**——直接答"Single → Multi → Harness 架构演进 + PE 自动化 + DPO 数据飞轮"。**真正的工程能力不在架构本身**，而在：PE 流水线化、LLM-as-a-Judge 偏差控制、DPO 训练闭环——把这三件事做出来，客服 Agent 才从"机械应答"变成"服务伙伴"。

## 一句话总结

智能客服 Agent 的演进路径是 Single → Multi → Harness，配套的是 PE 自动化流水线 + DPO 数据飞轮；架构不是设计出来的，是被业务复杂度逼出来的，工程能力的核心是让流水线自动化运转。