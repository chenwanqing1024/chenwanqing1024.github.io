---
title: 向量 RAG 退场，Agent 多轮检索接班
date: 2026-09-14
tags: [Agent, RAG, 向量检索, PostgreSQL, 读文笔记]
summary: 冯若航没宣布 RAG 死亡，他把"作为架构的 RAG"和"作为算子的向量召回"切开了——前者退场，后者降级。最硬的证据是 Claude Code 选了 grep 加 glob，资本选了 PG 而非向量库。文章把这个判断往前推一步：MCP 让检索从流水线变成随手可调的工具，这才是 RAG 退场的真正推手，不是窗口变大。
source-url: https://vonng.com/ai/rag-is-dead/
source-title: RAG 没死，但也快了
source-author: 冯若航
---

## 原文在说什么

冯若航（vonng，Pigsty / pgvector 重度玩家）标题写得很巧——"RAG 没死，但也快了"。正文里他做了一件更精确的事：**把"作为架构的 RAG"和"作为算子的向量召回"切开，前者退场，后者降级为默认算子**。这个词的发明者 Douwe Kiela（Contextual AI CEO）专门买了域名论证 RAG 没死，但他自家首页把 RAG 字样撤了——这个词的处境，可见一斑。

最硬的两处证据。一是 Claude Code 创造者 Boris Cherny 在 Latent Space 亲口说：他们试过 RAG、本地向量库、各种搜索工具，最后落在 agentic search 上，因为它"outperformed everything, by a lot"。Anthropic 后来把 `CLAUDE.md` + `glob` + `grep` + 渐进披露写进了方法论——**地表最强的 Coding Agent，最后选了 grep**。二是资本投票：Databricks 收 Neon（10 亿美元）、Snowflake 收 Crunchy Data（2.5 亿）、AWS 收 DuckLabs（DuckDB）——三年三家 PG / DuckDB 公司，一个向量库都没买；同期 Pinecone 在找下家。

论据链条很清楚：4K 窗口逼出的"切片→embedding→向量库→Top-K→塞 prompt"流水线，本质是应急方案。窗口到百万 token 后约束没了，它自己还有三条先天病根——**切片有损、Top-K 不能说"没有"、相似不等于相关**——一条 grep 加一个会多翻几轮的 Agent，正好各治一条。活下来的 RAG 已经不以向量为靶心，专用向量数据库的存在理由跟着走了一半。

## 我的看法

### 认同的部分：pipeline 被 MCP 解构，比窗口变大更致命

"向量召回从架构降级为算子"这个判断我完全同意。但我认为文章把原因归到"窗口变大"是表层归因——**真正的推手是 MCP**。MCP 没有标准化任何检索算法，它把"检索"从一条要专门搭的流水线变成了 Agent 随手可调的工具。一旦检索可以和其他工具并列在同一个协议层调用，pipeline 思维本身就崩了。Claude Code 选 agentic search 不是因为窗口够大——Claude Code 处理的是本地代码库，token 量从来不是瓶颈——而是因为模型自己决定"该不该 grep 该不该读全文"这件事，比把 Top-K 提前算好更对。

我自己做 RAG demo 的体感也是：从 2023 年搭 Chroma 加 LangChain，到 2025 年给 Agent 接一个 Postgres（同时挂 tsvector 加 BM25 和 pgvector 加向量），复杂度是下降的，**不是上升的**。因为不需要再为"我应该用哪个 chunk size"这个问题单独写一个评测脚本了。

### Push back：把"向量 RAG 退场"等同于"RAG 退场"过激了

文章的标题党把"RAG 没死"做成悬念，但正文自己承认中间档（20 万到几千万 token）的 RAG 依然有用，形态是 hybrid retrieval + reranker + 元数据过滤。这恰恰是我要 push back 的地方——**对企业知识库那种非结构化但又是高度精确的场景（错误码、合同条款、产品型号、人名），BM25 + reranker 的组合比 grep 强**。文章里那个"非结构化 grep 不管用"的反驳它自己也答了，但答得不响：Claude Code 能用 glob/grep 是因为代码本身是结构化文本、函数名变量名天然是关键字，**把 glob/grep 搬到企业知识库是另一回事**。Hybrid 不会消失，它只是不再以向量为核心。

### 加一个例子：Paimon / 数据湖仓的平行故事

文章最后把数据库重新定位为 Agent 的"状态平面"——LISTEN/NOTIFY 是信号总线、`SKIP LOCKED` 是任务队列、PITR + PG 18 的 CoW 克隆是回到过去和复制当下、ACID 是多 Agent 共享状态的最省心方案。这个框架我完全买账——它和我在数据湖仓领域看到的故事是同一个结构：**AI Native DB 不是新物种，是传统 DB 加 AI 能力**。Neon 的数字最杀：八成的数据库是 Agent 自动创建的，不是人建的。Agent 需要的是事务、回滚、分支、审计，不是向量索引。**没有身体的灵魂是幽灵，没有数据库的 Agent 是聊天机器人**——老冯这句写得狠但确实准。

## 一句话总结

向量 RAG 是 4K 窗口时代的应急方案，窗口大了它就该退场；活下来的不是 RAG 这个词，是 grep + BM25 + Agent 多轮检索的混合体——而数据库（不专指向量库）是这一切能跑起来的状态平面。