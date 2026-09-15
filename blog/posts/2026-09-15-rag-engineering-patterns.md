---
title: RAG 实战：从 Naive 到 Modular 的 5 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, RAG, Agent]
summary: 把 claude-cookbooks/capabilities/retrieval_augmented_generation 的 663KB 主教程 + Promptfoo 评测套件拆成 5 个工程模式：文档分块 / 检索选型 / 上下文注入与引用 / Promptfoo 评测闭环 / 架构演进路径。每个模式给出一行定位 + 最小代码 + 踩坑提示。
source-url: https://github.com/anthropics/claude-cookbooks/tree/main/capabilities/retrieval_augmented_generation
source-title: claude-cookbooks / capabilities / retrieval_augmented_generation
source-author: Anthropic
---

## 引子

`capabilities/retrieval_augmented_generation/` 是 Anthropic 官方给的 RAG 黄金标准教程：一个 663KB 主教程 + 完整的 Promptfoo 评测套件（`eval_retrieval.py` / `eval_end_to_end.py` / `vectordb.py`）+ 现成评测数据集（`docs_evaluation_dataset.json`）。它不仅讲"怎么做 RAG"，还讲"怎么测 RAG"——评测脚本本身比很多公司的 RAG 系统都完整。

这篇文章把它提炼成 5 个相互独立的工程模式，按"**文档 → 检索 → 注入 → 评测 → 架构**"排列。每个模式配最小代码 + 3 条以内工程踩坑提示。

---

## 1. 文档分块：按文档类型选策略

**一行定位**：分块不是"一刀切 512 token"，按文档结构选 chunking 策略。

**最小代码**（多策略分块器）：

```python
def chunk_document(doc: str, doc_type: str) -> list[str]:
    if doc_type == "markdown":
        # 按标题切，保留 H1/H2 边界
        return re.split(r'(?m)^#{1,3} ', doc)[1:]
    elif doc_type == "code":
        # 按函数/类边界切（用 tree-sitter 等）
        return split_by_ast(doc, lang="python")
    elif doc_type == "pdf":
        # 按页切，再合并相邻小段到 ~800 token
        return merge_pages(split_by_page(doc), target=800, model="claude")
    elif doc_type == "transcript":
        # 按说话人切换切，再加滑动窗口（避免边界信息丢失）
        return sliding_window(split_by_speaker(doc), window=5, stride=2)
    else:
        # 通用 fallback：递归字符分块
        return recursive_split(doc, chunk_size=512, overlap=64)
```

**工程提示**：

- **chunk_size 经验值**：中文 200-400 字 / 英文 512-1024 token。**太小**召回碎、上下文碎；**太大**噪音多、首 token 慢。
- **保留元数据**：每个 chunk 必须带 `source_doc_id`、`page_number` 或 `section_title`、`chunk_index`——没有这些做不了 citations，也做不了 retrieve 阶段的过滤。
- **HTML/Markdown 优先结构化分块**：别用通用 tokenizer 切 H1 标题——会切出"这是 Paimon 的核心优势"这种失语 chunk。

---

## 2. 检索选型：向量 / 关键词 / 混合

**一行定位**：retrieval 不是"embed 然后 top-k"，按查询类型选策略。

**最小代码**（混合检索 + 重排）：

```python
def hybrid_retrieve(query: str, k: int = 10):
    # 1. 向量召回
    vec_hits = vector_db.search(query, k=k*2)
    # 2. 关键词召回（BM25 / Elasticsearch）
    kw_hits = es.search(query, k=k*2)
    # 3. RRF 融合（Reciprocal Rank Fusion）
    fused = rrf_fusion(vec_hits, kw_hits)
    # 4. 重排（用 Cohere Rerank 或本地 cross-encoder）
    reranked = reranker.rerank(query, fused[:20], top_k=k)
    return reranked
```

**工程提示**：

- **没有"通用最佳 retrieval"**。代码检索要 AST-aware、对话检索要 sliding window、FAQ 检索 BM25 就够、跨语言检索要走 embedding。
- **重排贵但值得**。召回 50-100 个 chunk → rerank 到 top 5-10——准确率比"召回 top 5 直出"高一档，成本可接受。
- **过滤优于召回**。90% 的噪音可以用 metadata 过滤掉（时间范围、文档类型、权限标签）。先 filter 再 rank 比"大海捞针"省 90% token。

---

## 3. 上下文注入与引用：`using_citations.ipynb`（位于 misc/）

**一行定位**：检索到的 chunk 注入 prompt 时打开 citations，让回答自带出处。

**最小代码**：

```python
uploaded = client.beta.files.upload(file=open("manual.pdf", "rb"))

resp = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=2048,
    messages=[{
        "role": "user",
        "content": [
            # 把检索到的 top-5 chunks 当 document 块传（不是塞进 prompt 字符串）
            *[{"type": "document",
               "source": {"type": "text", "data": chunk.text},
               "title": f"{chunk.doc_id}#{chunk.page}",
               "citations": {"enabled": True}}
              for chunk in retrieved_chunks],
            {"type": "text", "text": user_query}
        ]
    }]
)

# 解析回答 + 引用
for blk in resp.content:
    if blk.type == "text":
        answer = blk.text
        citations = blk.citations   # char_location / page_location / content_block_location
```

**工程提示**：

- **document block 不是字符串**。`{"type": "document", ...}` 比拼字符串有三大优势：原生 citations、自动 OCR、可缓存。
- **chunk 之间要"标题 / 编号"明确**。模型看到 5 个匿名 chunk 会乱序总结；看到「第 3 节 / 第 12 页」会按结构引用。
- **prompt 要限制"只基于文档回答"**。否则 Claude 会用预训练知识补全，导致引用缺失——`system: "只基于以下文档回答，无法回答时说不知道"`。

---

## 4. Promptfoo 评测闭环：`evaluation/`

**一行定位**：把 RAG 的"检索质量"和"端到端答案质量"做成 CI 跑得动的回归测试。

**最小代码**（`evaluation/eval_end_to_end.py` 简化版）：

```python
import promptfoo as pf

# 1. 准备评测集（30-50 个问答对 + ground truth）
dataset = json.load(open("docs_evaluation_dataset.json"))

# 2. provider：你的 RAG pipeline
def rag_provider(prompt: str) -> str:
    chunks = hybrid_retrieve(prompt, k=5)
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        messages=[{"role":"user","content":[
            *[{"type":"document","source":{"type":"text","data":c.text}}
              for c in chunks],
            {"type":"text","text": prompt}
        ]}]
    )
    return resp.content[0].text

# 3. 评测指标
test_cases = [
    {"prompt": q["question"],
     "assert": [
        {"type":"contains","value": q["must_contain"]},    # 必须含关键事实
        {"type":"llm-rubric","value": q["rubric"]},        # LLM 当裁判打分
        # 还可以加 "context-faithfulness"（答案必须基于 context）
     ]}
    for q in dataset
]

# 4. 跑回归
pf.run(test_cases, providers=[rag_provider])
```

**配套：`eval_retrieval.py`** 单独评测 retrieve 阶段：

```python
# 召回指标（不依赖生成）
assertions = [
    {"type":"contains-any","value": q["relevant_chunk_ids"]},  # 必须召回到相关 chunk
    {"type":"metric","value": "recall@5"},                      # top-5 召回率
    {"type":"metric","value": "mrr"},                           # Mean Reciprocal Rank
]
```

**工程提示**：

- **评测集必须冻结**。50 条问答对用 6 个月 — 改 prompt、加文档、换模型都跑这 50 条，**改动前先看 baseline 不退化**。
- **评测要拆两个**。`eval_retrieval`（只评检索）和 `eval_end_to_end`（评整体）分开跑——前者 1 分钟跑完、后者 10 分钟。检索退化和生成退化要能区分开。
- **加一个"no-answer 评测集"**。20 条「文档里没有答案」的查询——RAG 必须说"不知道"而不是编。**这是 RAG 系统最容易暴露幻觉的地方**。

---

## 5. 架构演进：Naive → Advanced → Modular

**一行定位**：RAG 架构分三阶段演进，不要一开始就上 modular。

| 阶段 | 架构 | 触发条件 |
|---|---|---|
| **Naive** | Embed → Top-k → Prompt | 1-10 个文档、用户 <100 |
| **Advanced** | 加 query rewriting / re-ranking / metadata filter | 文档 10-1000、用户 >1000 |
| **Modular** | query 路由 + 多个 retriever + 后处理 pipeline | 文档类型多 / 多租户 / 跨语言 |

**Modular 最小代码骨架**：

```python
class RAGPipeline:
    def __init__(self):
        self.rewriter = QueryRewriter()      # 查询改写 + HyDE
        self.routers = [                     # 查询路由：不同类型走不同 retriever
            CodeRouter(), DocsRouter(), FAQRouter()
        ]
        self.retrievers = {
            "code": ASTRetriever(),
            "docs": HybridRetriever(),
            "faq": BM25Retriever()
        }
        self.reranker = CrossEncoderReranker()
        self.generator = ClaudeGenerator()

    def query(self, q: str) -> str:
        rewritten = self.rewriter(q)
        route = self.routers[0].route(rewritten)
        chunks = self.retrievers[route].retrieve(rewritten, k=20)
        chunks = self.reranker.rerank(rewritten, chunks, top_k=5)
        return self.generator.generate(rewritten, chunks)
```

**工程提示**：

- **不要 premature modularize**。Naive 阶段把 eval 跑起来、把 RAGAS 之类的指标做正，再考虑加模块。每个新模块都要先证明它能提升指标。
- **Modular 的本质是"决策点显式化"**。重写一次查询还是改 prompt？路由到代码还是文档？这些隐式决策一旦显式，调试 / 替换 / A/B 都变得简单。
- **多租户 RAG 的最大坑是数据隔离**。同一 pipeline、不同 namespace 的 vector DB——不要尝试"同一库 + metadata filter"，**会泄漏**。

---

## 落地清单

| 阶段 | 优先加入 | 解决的问题 |
|---|---|---|
| 第一个 demo | #1 基础分块、#3 注入 + citations | 能跑通 + 可解释 |
| 100 个用户 | #2 混合检索、#4 Promptfoo 评测 | 召回质量 + 回归 |
| 1000 个用户 | #1 文档类型分块、#5 naive → advanced | 召回稳定性 |
| 10000 个用户 | #5 modular 路由、#4 no-answer 评测集 | 多源 + 抗幻觉 |

## 与其它模式的关系

- **tool_use**：RAG 的"检索工具"就是 `query_db` / `search_docs`——RAG 是 tool_use 的子集。当 RAG 之外还要调其它工具，就升级到 Agent。
- **extended_thinking**：复杂多跳推理（multi-hop RAG）开 thinking，单跳查询不需要。
- **prompt caching**：RAG 的 query + system 可以缓存，retrieved chunks **不能**（每次不同）。缓存可省 30-50% input token。
- **claude_agent_sdk**：当 RAG 需要"先搜文档、再查 DB、再调 API"时，升级到 Agent SDK 编排。

参考资料：

- [claude-cookbooks RAG 目录](https://github.com/anthropics/claude-cookbooks/tree/main/capabilities/retrieval_augmented_generation)
- [Promptfoo 框架](https://promptfoo.dev/)
- 配套：[tool_use 7 模式](blog/posts/2026-09-15-tool-use-engineering-patterns.md)、[claude_agent_sdk 5 模式](blog/posts/2026-09-15-claude-agent-sdk-engineering.md)