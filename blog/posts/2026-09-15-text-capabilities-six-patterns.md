---
title: 文本能力 6 个实战模式：classification / moderation / contextual-embeddings / knowledge_graph / summarization / text_to_sql
date: 2026-09-15
tags: [Claude, AI 工程, NLP]
summary: 把 claude-cookbooks/capabilities 里除 RAG 之外的 6 个子目录提炼成各自的最小落地模式。每个能力一行定位 + 最小代码 + 3 条以内踩坑提示，附选型对照表。
source-url: https://github.com/anthropics/claude-cookbooks/tree/main/capabilities
source-title: claude-cookbooks / capabilities
source-author: Anthropic
---

## 引子

`capabilities/` 目录下除了 RAG（已单写一篇）还有 6 个文本能力子目录：classification、content_moderation、contextual-embeddings、knowledge_graph、summarization、text_to_sql。每个目录都有一个完整教程 notebook + 评测脚本，构成"开箱即用"的能力模板。

这篇文章把它们压成 6 个相互独立的最小模式，按"**判别 → 安全 → 富化 → 结构化 → 压缩 → 接口化**"排列。每个模式一行定位 + 最小代码 + 2-3 条工程踩坑提示。

---

## 1. Classification（文本分类）

**一行定位**：用 `tool_use` 强制 schema，把"情感 / 主题 / 意图"打成结构化标签。

**最小代码**：

```python
tool = {
    "name": "classify",
    "input_schema": {
        "type": "object",
        "properties": {
            "label": {"type": "string",
                      "enum": ["billing", "tech_support", "sales", "other"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}
        },
        "required": ["label", "confidence"]
    }
}
resp = client.messages.create(model="claude-haiku-4-5", tools=[tool],
                              tool_choice={"type": "tool", "name": "classify"},
                              messages=[{"role":"user","content": text}])
# low confidence 进人工
label, conf = parse_tool_use(resp)
if conf < 0.7:
    escalate_to_human()
```

**工程提示**：

- 用 **Haiku** 做分类：速度 < 200ms，成本 < 1¢/千条。Sonnet 留给生成任务。
- **label 集合 ≤ 7 个**。多了准确率掉得厉害——多分类就分两轮（先大类、再小类）。
- **confidence < 0.7 转人工**，不要硬拒。这是客服 / 路由系统的标准做法。

---

## 2. Content Moderation（内容审核）

**一行定位**：双层防线——Haiku 关键词粗筛 + Sonnet 复杂判断，落到 `pipeline.py` 风格的多级流水线。

**最小代码**：

```python
# 第一层：Haiku 高速粗筛（< 200ms）
flag1 = haiku_classify(text, categories=["safe","hate","sexual","violence","pii"])
if flag1 == "safe":
    return approve()

# 第二层：Sonnet 复杂判断（仅对命中样本）
flag2 = sonnet_classify(text, context=context_window)
if flag2 != "safe":
    audit_log.record(text, flag2)
    return reject(flag2)
```

**工程提示**：

- **Haiku 做全部审核不实际**（漏判率高），**Sonnet 做全部审核太贵**（成本 ×10）。双层是工业界标准做法。
- **审核策略要白盒可审计**。不要让 Claude 自己决定"为什么拒"——给它一个固定的 taxonomy + 决策树，输出枚举值。
- **人工审核兜底永远要有**。任何 LLM 审核漏判率都不是 0%——给高风险操作留人工通道。

---

## 3. Contextual Embeddings（上下文增强 Embedding）

**一行定位**：把每个 chunk 的"全局上下文"通过 Claude 提炼后再 embed，显著提升 RAG 召回率。

**最小代码**：

```python
async def contextualize_chunk(chunk: str, full_doc: str) -> str:
    """给 chunk 补一段'它在整个文档中的位置'的描述"""
    prompt = f"""用 50-100 字描述下面这段文本在整篇文档中的位置和上下文，
    使得这段文本独立可理解（无全文也能看懂它在说什么）：
    
    【整篇文档】
    {full_doc[:3000]}
    
    【目标段落】
    {chunk}
    
    【上下文描述】"""
    resp = await haiku_client.messages.create(
        model="claude-haiku-4-5", max_tokens=200,
        messages=[{"role":"user","content": prompt}]
    )
    context_summary = resp.content[0].text
    return f"[Context: {context_summary}]\n\n{chunk}"   # 拼接后再 embed

# 写入向量库前先 contextualize
chunks_with_context = [await contextualize_chunk(c, doc) for c in chunks]
vector_db.add(chunks_with_context)
```

**工程提示**：

- 召回率提升 **30-50%**（Anthropic 论文数据），代价是每 chunk 多一次 Haiku 调用 + 50-100 token 的"上下文污染"风险——做 A/B 验证。
- **context_summary 要"独立可理解"**。否则下游 LLM 拿到的是带幻觉上下文的 chunk，反而误导回答。
- 用 **Haiku** 而不是 Sonnet 做 contextualize——这一步是批处理，可并行、便宜优先。

---

## 4. Knowledge Graph（知识图谱抽取）

**一行定位**：用 Claude 从文本里抽（实体、关系、三元组），落到 Neo4j 或内存图里做推理。

**最小代码**：

```python
tool = {
    "name": "extract_triples",
    "input_schema": {
        "type": "object",
        "properties": {
            "triples": {"type": "array",
                        "items": {"type": "object",
                                  "properties": {
                                      "head": {"type": "string"},
                                      "relation": {"type": "string"},
                                      "tail": {"type": "string"}},
                                  "required": ["head","relation","tail"]}}}
        }
    }
}
resp = client.messages.create(model="claude-sonnet-4-6",
                              tools=[tool],
                              tool_choice={"type":"tool","name":"extract_triples"},
                              messages=[{"role":"user","content": document}])
triples = parse_tool_use(resp)["triples"]

for h, r, t in triples:
    graph.upsert(h, r, t)   # 落到 Neo4j / NetworkX
```

**工程提示**：

- **关系抽取的 schema 决定质量上限**。"`relation` 是动词短语、且必须在 {工作于、收购、参股、投资…} 这个枚举里`"——这种硬约束比"提取所有关系"准确率高一个数量级。
- **批处理 + 增量更新**。不要每次文档变更全量重抽——只对 diff 部分重新跑图谱更新。
- **知识图谱 ≠ 万能**。结构化查询、关系推理是强项；非结构化问答还是 RAG 更便宜。两者配合用（KG 做"硬查询"、RAG 做"软检索"）。

---

## 5. Summarization（文本摘要）

**一行定位**：摘要不是"把全文变短"，是按目标粒度（句子/段落/章节/全文）和目标受众（专家/小白）定制。

**最小代码**（多视角摘要）：

```python
prompt_template = """请用以下视角总结文档：
- 视角：{perspective}
- 长度：{length}
- 受众：{audience}

【文档】
{document}

【摘要】"""

# 一次 API 调用拿多个摘要（省钱）
resp = client.messages.create(model="claude-haiku-4-5",
    messages=[{"role":"user","content": prompt_template.format(
        perspective="产品经理视角，关注商业影响",
        length="200字",
        audience="非技术高管",
        document=doc)}])
```

**工程提示**：

- **摘要必须保留"实体 + 数字 + 时间"**。否则摘要会失去可验证性——用户在原文里找不到。
- **摘要不是预处理**。很多人把摘要当 RAG 的预处理——错。摘要会丢信息，**RAG 应该用原文 + 选择性引用**，不要摘要替代。
- 长文档（> 50K token）走 **map-reduce 摘要**：先每段总结成 200 字，再把 200 字串起来总结——比一次性"总结整篇"保真度高 30%。

---

## 6. Text-to-SQL（自然语言转 SQL）

**一行定位**：用 tool_use 把 schema + 自然语言映射成 SQL，服务端校验后再执行。

**最小代码**：

```python
tool = {
    "name": "generate_sql",
    "description": """Generate a read-only SQL query against the analytics DB.
Tables:
  users(id BIGINT, email TEXT, created_at TIMESTAMP, country TEXT)
  orders(id BIGINT, user_id BIGINT, amount DECIMAL, created_at TIMESTAMP)
Constraints:"" + read_only_constraint_text,
    "input_schema": {"type":"object",
                     "properties":{"sql":{"type":"string"}},
                     "required":["sql"]}
}
resp = client.messages.create(model=..., tools=[tool],
                              tool_choice={"type":"tool","name":"generate_sql"},
                              messages=[{"role":"user","content": user_query}])

# ⚠️ 关键：服务端校验 + 只读执行，不要相信生成的 SQL
sql = parse_tool_use(resp)["sql"]
if not is_select_only(sql):            # 白名单：只允许 SELECT / WITH
    raise SecurityError()
if not has_limit(sql, max_rows=1000):  # 必须有 LIMIT
    sql = inject_limit(sql)
result = db.execute(sql)
```

**工程提示**：

- **绝对不要让 Claude 生成的 SQL 直接跑生产 DB**。服务端必须做：① SELECT 白名单；② 强制 LIMIT；③ schema 校验（表/列存在）；④ 资源超时。
- **schema 别全贴 prompt**。几百张表直接撑爆——给 Claude 一个 `list_tables()` 工具，让它先问再查。
- **加一个"query explainer"中间层**。用户问"为什么这个 SQL 慢"，让 Claude 解读 EXPLAIN 结果并改写——这是 Text-to-SQL 的高阶用法。

---

## 选型对照表

| 能力 | 触发场景 | 模型 | 关键工程要素 |
|---|---|---|---|
| **classification** | 客服路由 / 标签 | Haiku | enum 限制 + 置信度阈值 |
| **content_moderation** | UGC / 评论 | Haiku + Sonnet 双层 | 双层防线 + taxonomy |
| **contextual-embeddings** | RAG 召回优化 | Haiku（批处理） | 召回率 +30% |
| **knowledge_graph** | 结构化查询 / 推理 | Sonnet | 关系枚举约束 |
| **summarization** | 长文档浓缩 | Haiku | map-reduce + 实体保留 |
| **text_to_sql** | 自然语言查 DB | Sonnet | 服务端校验 + LIMIT 强制 |

## 落地清单

| 项目阶段 | 优先加入 | 理由 |
|---|---|---|
| 第一个文本功能 | classification | 最低成本 + 最高可见价值 |
| 上线前 | content_moderation | 法务兜底 |
| RAG 召回不达标 | contextual-embeddings | 召回率提升杠杆 |
| 结构化数据丰富 | knowledge_graph | 增量图谱更新 |
| 长文档场景 | summarization | map-reduce 保真 |
| 内部 BI / 自助分析 | text_to_sql | 服务端校验是红线 |

## 与其它模式的关系

- **classification 是 tool_use 的子集**：[tool_use 7 模式](blog/posts/2026-09-15-tool-use-engineering-patterns.md) 里的 `extracting_structured_json` 直接覆盖。
- **contextual-embeddings 是 RAG 的召回优化器**：[RAG 5 模式](blog/posts/2026-09-15-rag-engineering-patterns.md) 的 #2 检索选型可以接它。
- **text_to_sql 是 tool_use + 安全约束的组合**：参考 [claude_agent_sdk 5 模式](blog/posts/2026-09-15-claude-agent-sdk-engineering.md) 的 MCP 集成模式，把 SQL 工具通过 MCP 暴露。

参考资料：

- [claude-cookbooks/capabilities](https://github.com/anthropics/claude-cookbooks/tree/main/capabilities)
- 配套阅读： [tool_use 7 模式](blog/posts/2026-09-15-tool-use-engineering-patterns.md)、[RAG 5 模式](blog/posts/2026-09-15-rag-engineering-patterns.md)