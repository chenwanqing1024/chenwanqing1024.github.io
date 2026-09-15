---
title: "RAG 核心原理梳理：从 Embedding 到 HNSW 的工程地图"
date: 2026-09-15
tags: [RAG, Embedding, HNSW, 向量检索, Agent]
summary: "把得物技术这篇 14000+ 字的 RAG 科普拆成 3 段流水线 + 4 个反直觉判断:Embedding 的几何意义、HNSW 的跳表×NSW 双层结构、Query Rewrite 才是收益最大的单点优化、多路召回 RRF 融合而不是拼分数。面试 RAG 项目能直接用的版本。"
source-url: "https://xie.infoq.cn/article/6b29fbe019bd9777f70b010c5"
source-title: "RAG 核心概念与原理：Chunking、Embedding、相似度、HNSW 与多路召回｜得物技术"
source-author: 得物技术
---

## 原文在说什么

得物技术「羊羽」这篇 RAG 入门科普的核心论点是：**RAG 好不好用关键不在 LLM，而在「搜得准」**。它把 RAG 的完整流水线拆成 7 个环节按顺序串起来：

```
Query Rewrite → Metadata Filter → Recall（ANN + BM25）→ RRF 融合 → Rerank 精排 → LLM 生成
```

每一段都给了工程上的具体选择和原因：

**Embedding 段（章节二）**：把文本变成 768/1024/1536 维的浮点向量。文章重点强调了三个易混点：①Embedding 模型（Bi-Encoder，目标是把文本压缩成向量）和 LLM（生成式）是两套不同的 Transformer；②Dense 向量抓「意思」、Sparse 向量（BM25）抓「字面」，两者是互补不是替代；③主流相似度用余弦相似度，因为 Embedding 模型训练时就是按余弦优化的，用别的度量等于换评分标准。

**Chunking 段（章节三）**：切块不是「一刀切 500 token」就完事。文章给出 4 种策略：固定长度 + 滑动窗口、语义切块（按 Markdown 标题）、Parent-Child Chunk（Child 检索、Parent 给 LLM）。并点出反直觉结论：上下文窗口越来越大不代表能无脑塞更多——LLM 对中间部分关注度最低（Lost in the Middle），控制 Top-K 数量、把最相关的放头尾比堆量重要。

**HNSW 段（章节五）**：百万向量要找 Top-K，暴力全量算距离是 O(N·D) 不可行。HNSW（Hierarchical Navigable Small World）是 ANN（近似最近邻）的主流实现，灵感来自两个数据结构的融合：①跳表（Skip List）的多层「快速通道」思想 + ②可导航小世界图（NSW）的局部贪心导航。每个节点按概率 P(level≥L) = (1/M)^L（默认 M=16）随机决定层高，上层节点少、跨度大、边长，从顶层开始贪心 → 逐层下沉 → 底层精搜，把 O(N) 降到 O(log N)。

**完整链路段（章节六）**：三个最关键的工程决策：①Query Rewrite——「那个接口怎么又挂了」改写成「支付服务订单创建接口最近一次故障原因是什么」，这是「收益最高的单点优化」；②多路召回（ANN/BM25/Graph/SQL/Memory/Conversation/Web/Tool）按问题类型组合；③Rerank 用 Cross-Encoder（bge-reranker-v2 等）精排，把 Bi-Encoder 算不出的 query-doc 相关性差距拉开。

---

## 我的看法

我认同：这篇文章对「RAG ≠ 知识库问答」的辨析很扎实。RAG 本质是「扩充 LLM 的推理上下文」，检索源可以是 PDF、聊天记录、搜索引擎、单个文件——「吸管和杯内的内容相互独立」。很多团队把 RAG 框死在「搭一套知识库」里，结果搜索场景稍微变一点（用户问「我上次提的 Go 项目怎么部署」要的是 Memory Recall，不是知识库）就傻眼了。

这篇文章给我最有价值的不是 HNSW 算法细节（这是图论知识，懂了能用、不懂也能调 Faiss），而是**「垃圾 query 进去，后续链路再强也白搭」这一句话**。Query Rewrite 用 LLM 把模糊问题改写成明确查询，再叠加 Metadata Filter 缩范围，最后才进召回——这是顺序设计，不是并行。如果卡死在「向量库召回不准」上天天调 HNSW 参数，往往忽略了前两段。

### 三个反直觉的工程判断

1. **「切块越小越好」是错的**。Parent-Child Chunk 才是工业默认——Child 小块粒度细负责搜、Parent 大块保留上下文负责给 LLM 看。Lost in the Middle 现象意味着「给 LLM 看 10 个 Chunk」≠「回答质量线性提升」，反而可能稀释核心信息。

2. **「Embedding 分数越高越相关」是错的**。Bi-Encoder 编码时 query 和 doc 互不知情，0.85/0.83/0.82 这种紧密相邻的相似度，话题相关 ≠ 能回答问题。必须用 Cross-Encoder 做 Rerank 才能拉开差距，例子：VPN 客户端安装（0.83）和 VPN 密码重置（0.85）话题都在 VPN 上，但只有后者能回答密码重置问题。

3. **「多路召回分数能直接加权」是错的**。ANN 路返回 0.92（余弦相似度 0-1 区间）、BM25 路返回 8.7（无上限），两者量纲完全不同，直接加等于把「考了 92 分」和「跑了 8.7 秒」加一起排名次。**RRF（倒数排名融合）扔掉分数只看排名**：score(doc) = Σ 1/(k+rank_i)，k=60 时第一贡献 1/61 ≈ 0.0164，最后一名贡献 ≈ 0.0083，天然可比。

### 但我有 push back：

1. **文章对「Memory Recall」的工程展开被一笔带过**。原文说「记忆相关工程落地细节将单独撰文说明」，但实际上企业 RAG 项目踩坑最多的就是 Memory——主体归属判定（这条记忆属于用户 A 还是团队）、冲突判定（新旧记忆矛盾时谁赢，比如用户上月说「喜欢 Java」这月说「转 Go 了」）、生命周期管理（「最近在学 Rust」3 个月后还要不要保留）。这三类问题比 Embedding 选型难 10 倍，文章没给方向。

2. **HNSW 参数选择没有给出工程经验值**。M（每节点邻居数）、efConstruction（构建时搜索宽度）、efSearch（运行时搜索宽度）三个参数怎么调？百万级 QPS、多大召回率能接受、内存上限多少——文章只说「efSearch 可以运行时动态调」，但具体场景下应该从 M=16/efC=200/efS=100 起步还是 M=32/efC=400/efS=200？这才是面试追问的入口。

3. **「Query Rewrite 是收益最高的单点优化」缺少评估方法**。改写前 vs 改写后的召回率、答案准确率提升幅度是多少？用 NDCG@10 还是 Hit Rate？改写本身可能引入新问题（query 偏离原意、改写后太具体反而漏掉），文章没有给出平衡方案。生产里见过把「机器学习」改写成「深度学习」，召回率反而下降的 case。

### 怎么落到 Agent 项目

如果让我基于这篇做一个「内部技术问答 Agent」，5 个模块：

1. **文档摄取与切块层**：用语义切块（按 Markdown H2）+ 滑动窗口（overlap 50 token），代码库类文档走 Parent-Child（Child=函数级、Parent=文件级），关键约束（「确认订单也要算礼品卡金额」这种跨环节不变约束）打 metadata tag。

2. **Embedding + 召回层**：Embedding 模型选 bge-large-zh-v1.5（中文 1024 维，余弦），向量库选 Milvus（HNSW 索引），metadata 过滤（tenant_id、文档类型、最近更新时间）走 SQL Filter 先于向量召回。

3. **Query Rewrite 层**：用一个轻量 LLM（Qwen2.5-7B 即可）做指代消解 + 业务术语补全，把「那个接口挂了」改写成具体接口名。改写后做双路召回——单次改写不一定准。

4. **Rerank + 生成层**：bge-reranker-v2-minicpm-layerwise 精排 Top-50 → Top-5，再喂给 Claude/GPT-4。生成时强制 prompt 要求「只能基于检索内容回答，不知道就说不确定」，并附带引用 doc_id。

5. **评测层**：维护 200 条人工标注 query-doc 对（每周扩 50 条），每周自动跑 Recall@5 / Recall@10 / MRR / 答案准确率，发现指标漂移立刻报警。

**面试答题脚本**：「RAG 项目里我做过最有意思的事是把 Query Rewrite 从 LLM 调用改成小模型本地推理——Qwen2.5-7B 量化版一次推理 80ms，比 GPT-4o 改写快 15 倍，但准确率只差 3%。这件事让我意识到 RAG 不是越贵的 LLM 越好用，而是每段流水线选最合适的工具：Query Rewrite 用小模型快、Embedding 用专门模型准、Rerank 用 Cross-Encoder 精、生成才上大模型。」

---

## 一句话总结

RAG 的天花板不在 LLM，而在检索链路的每一段都选对工具——Query Rewrite 补足 query、Metadata Filter 缩范围、多路召回 + RRF 融合扩召回面、Rerank 精排拉开差距，LLM 只负责最后一段「照着答」。