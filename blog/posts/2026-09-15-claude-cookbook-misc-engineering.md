---
title: Claude API 工程实战：从 claude-cookbooks/misc 提炼的 14 个最小可用模式
date: 2026-09-15
tags: [Claude, AI 工程, LLM]
summary: 把 anthropics/claude-cookbooks 的 misc 目录拆成 14 个独立模式，按「成本/输出可控/质量保障/长上下文/工作流增强」五个主题分组，每条给出一行定位 + 最小代码 + 工程踩坑提示。所有代码对齐 anthropic-sdk-python ≥ 0.40 的当前接口。
source-url: https://github.com/anthropics/claude-cookbooks/tree/main/misc
source-title: claude-cookbooks / misc
source-author: Anthropic
---

## 引子

`anthropics/claude-cookbooks` 是官方维护的「代码即文档」仓库，把 Claude API 的高频用法拆成可复制粘贴的 Jupyter notebook。`misc/` 是其中一个「杂项但重要」目录：14 个 notebook，覆盖成本、缓存、批处理、JSON 约束、引用、PDF、SQL 工具、元提示、评估、长会话压缩等关键工程议题，每个都只解决一个问题，可以单独拆下来塞进你自己的项目。

这篇文章不谈原理（notebook 自己讲得很清楚），只挑出每个 notebook 在生产环境里**最常用的那一招**，附上最小代码片段和工程落地提示。所有代码基于 `anthropic-sdk-python` 当前接口（`>= 0.40`），与最新 SDK 直接对齐。

---

## 一、成本与性能：把单次调用变得便宜又稳

### 1. `prompt_caching.ipynb` — 把可复用的前缀钉死

**最小用法**：给 system、tools、长文档开头打一个 `cache_control` 断点，重复前缀 5 分钟内自动命中，价格只有写入的 1/10。

```python
from anthropic import Anthropic
client = Anthropic()
LONG_SYSTEM = open("system_prompt.md").read()  # 大段稳定的指令/规则

resp = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    system=[
        {"type": "text", "text": LONG_SYSTEM,
         "cache_control": {"type": "ephemeral"}}   # ← 唯一一行启用缓存
    ],
    messages=[{"role": "user", "content": "今天的待办？"}],
)
print(resp.usage)  # 关注 cache_creation_input_tokens / cache_read_input_tokens
```

**工程提示**：

- TTL 默认 5 分钟；如需 1 小时，加上 `extended-cache-ttl` beta header 并设 `ttl: "1h"`。
- 缓存是按**整段前缀**匹配的：system → tools → 历史消息，任何一处字符差异就会 miss。建议把**变动最大的部分**（如对话历史）放在最末尾，缓存前缀越靠后命中率越稳。
- 用 `client.beta.messages.count_tokens()` 配合 `diagnostics={"previous_message_id": ...}` 可以拿到「为什么没命中」的具体原因（model 变了、tools 变了等），调试时必开。

### 2. `speculative_prompt_caching.ipynb` — 让首 token 提前出来

**最小用法**：在 tools 列表上挂 cache_control，让 Claude 在思考阶段就开始返回首个 token。

```python
tools = [
    {"name": "search_docs", "description": "...", "input_schema": {...},
     "cache_control": {"type": "ephemeral"}},   # ← 工具定义也可以缓存
    # ...其它工具
]
```

**工程提示**：适合**工具列表经常变更、但用户问题会反复问同一组工具**的场景（如客服 Agent）。常见反模式是给所有工具都加缓存 — 实测命中率提升有限，反而浪费 25% 的写入价。

### 3. `batch_processing.ipynb` — 异步任务直接打 5 折

**最小用法**：把所有可以容忍「24 小时内完成」的请求打包成 batch。

```python
batch = client.beta.messages.batches.create(
    requests=[
        {"custom_id": f"job-{i}",
         "params": {"model": "claude-haiku-4-5",
                    "max_tokens": 512,
                    "messages": [{"role": "user", "content": q}]}}
        for i, q in enumerate(questions)
    ]
)

# 轮询直到结束
while batch.processing_status != "ended":
    batch = client.beta.messages.batches.retrieve(batch.id)

# 拉结果（JSONL 流式）
for line in client.beta.messages.batches.results(batch.id):
    handle(line)   # line.result.message 即正常 message
```

**工程提示**：

- 价格是同步 API 的 50%，但**没有流式、首 token 延迟 1 小时级别**。只用于离线场景：日志摘要、批量标注、CI 里跑评测。
- 配合 Python worker 进程 + 失败重试，是评估/评测系统的标配管线。

---

## 二、输出可控：让 Claude 严格按格式说话

### 4. `how_to_enable_json_mode.ipynb` — 用 tool_use 替代正则

**最小用法**：不要在 prompt 里写「请输出 JSON」，直接注册一个空操作的 tool，schema 即契约。

```python
tools = [{
    "name": "emit_structured",
    "description": "Return the result as JSON.",
    "input_schema": {
        "type": "object",
        "properties": {
            "label": {"type": "string", "enum": ["pos", "neg", "neutral"]},
            "score": {"type": "number", "minimum": 0, "maximum": 1}
        },
        "required": ["label", "score"]
    }
}]

resp = client.messages.create(model="claude-sonnet-4-6",
                              tools=tools,
                              tool_choice={"type": "tool", "name": "emit_structured"},
                              messages=[{"role":"user","content": text}])

# 解析
for blk in resp.content:
    if blk.type == "tool_use" and blk.name == "emit_structured":
        data = blk.input   # 已是 dict，无需 json.loads
```

**工程提示**：

- `tool_choice={"type": "any"}` 强制调用但不限制工具；`{"type": "tool", "name": "..."}` 强制指定。
- `strict: True`（部分模型支持）开启后 schema 解析严格匹配，连 enum 之外的值都不返回。
- **不要再用 prompt 引导 + 正则抓 JSON** 的老办法 — 模型对 tool_use 严格度已经足够，正则反而成了易碎层。

### 5. `using_citations.ipynb` — 让回答自带出处

**最小用法**：传文档块时打开 citations，返回的 text block 自带引用。

```python
resp = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{
        "role": "user",
        "content": [
            {"type": "document",
             "source": {"type": "file", "file_id": uploaded.id},
             "title": "Product Spec",
             "citations": {"enabled": True}},     # ← 关键
            {"type": "text", "text": "总结这份文档的关键风险"}
        ]
    }]
)
# resp.content[*].citations 即引用列表
```

**工程提示**：

- 引用类型有 `char_location`（精确到字符）、`page_location`（精确到 PDF 页）、`content_block_location`（精确到 block）。前端的悬浮引用按类型选择渲染方式。
- 做 RAG 客服时，配合 code execution 让模型先查数据库、再引用文档，回答可追溯性直接拉满。

### 6. `sampling_past_max_tokens.ipynb` — 长输出分多次接续

**最小用法**：当 `stop_reason == "max_tokens"` 时，把已生成的文本作为 prefix 让模型继续。

```python
parts = []
while True:
    resp = client.messages.create(model="claude-sonnet-4-6",
                                  max_tokens=2048,
                                  messages=[{"role":"user","content": prompt}])
    parts.append(resp.content[0].text)
    if resp.stop_reason != "max_tokens":
        break
    # 把上一次输出回灌进 prompt，让模型接着写
    prompt = f"{prompt}\n\n[...continued]\n{resp.content[0].text}"
full = "\n".join(parts)
```

**工程提示**：

- 不优雅但有效。适合写长文档、长报告、长翻译这种「输出 > 模型上限」的场景。
- 更现代的做法是直接用 `client.messages.count_tokens()` 估算一次性输出所需 max_tokens，只要 ≤ 模型的 8K/128K 上限就别分段 — 多段会让模型丢失前文风格一致性。

---

## 三、质量保障：让 Claude 在生产里不退化

### 7. `building_evals.ipynb` — 用 Claude 当裁判

**最小用法**：拿更强的模型给弱模型的输出打分，跑回归。

```python
judge = client.messages.create(
    model="claude-opus-4-7",   # 裁判用最强的
    tools=[{
        "name": "rate",
        "input_schema": {"type": "object",
            "properties": {"score": {"type":"integer","minimum":1,"maximum":5},
                           "reason": {"type":"string"}},
            "required":["score","reason"]}
    }],
    tool_choice={"type":"tool","name":"rate"},
    messages=[{"role":"user","content":
        f"Rate the following answer (1-5):\nQuestion: {q}\nAnswer: {a}\n"
        f"Reference: {ref}"}]
)
score = next(b for b in judge.content if b.type=="tool_use").input["score"]
```

**工程提示**：

- 裁判模型要**显著强**于被评模型，否则评分会聚拢到中位数。
- 给裁判的 prompt 必须包含**具体打分维度**（准确、完整、风格、安全）而不是笼统「好不好」。
- 把每次评分结果存进 BigQuery / DuckDB，跑 PR 时回归，是 LLM 应用 CI 的核心。

### 8. `generate_test_cases.ipynb` — 用 Claude 造评测集

**最小用法**：给定真实样例，让 Claude 反向生成「刁钻问题 + 标准答案」。

```python
# 输入：5 个真实 query-answer 对
# 输出：50 个变体问题（边界、否定、罕见实体、风格反转）
```

**工程提示**：

- 配合 [anthropic/courses](https://github.com/anthropics/courses) 的 Building Effective Agents 一起用，先有 eval 集再去改 prompt。
- **不要**让生成的测试集进入训练集 — 会导致自评闭环。先冻结评测集，每次 prompt 改动都跑全量回归。

### 9. `building_moderation_filter.ipynb` — 内容审核的双层防线

**最小用法**：对所有用户输入先跑一遍 Haiku 分类器，命中就拒。

```python
flag = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=10,
    messages=[{"role":"user","content":
        f"Classify this into one of [safe, hate, sexual, violence, pii]:\n{user_input}"}]
).content[0].text.strip()
if flag != "safe":
    return reject(flag)
```

**工程提示**：

- Haiku 走审核性价比最高，延迟 < 200ms，成本 < 1¢/千次。
- 双层防线：第一层 Haiku 关键词粗筛，第二层 Sonnet 复杂判断。不要让 Sonnet 做全部审核 — 成本会爆炸。

---

## 四、长上下文与会话：突破 token 墙

### 10. `session_memory_compaction.ipynb` — 滑动窗口 + 摘要压缩

**最小用法**：超过阈值时，把最旧的 5 轮对话用 Claude 压缩成 200 字摘要，作为单条消息塞回历史。

```python
def compact(messages, threshold_tokens=80_000):
    if token_count(messages) < threshold_tokens:
        return messages
    old = messages[:-5]   # 留 5 轮最新
    summary = summarize(old)   # 调一次 Claude
    return [{"role":"user","content":f"[历史摘要]\n{summary}"}] + messages[-5:]
```

**工程提示**：

- 摘要 prompt 必须保留**实体、决策、未完成任务**三要素，否则模型会失忆。
- 更高级玩法：把摘要当作 long-term memory 存进向量库，下次只 retrieve 相关片段（参见 `capabilities/retrieval_augmented_generation`）。
- 配合 SDK 的 `BetaCompactionBlock`（新版已内置）可以直接用，不需要自己写摘要循环。

### 11. `pdf_upload_summarization.ipynb` — Files API 上传长 PDF

**最小用法**：用 `client.beta.files.upload` 拿到 file_id，再当 document block 用。

```python
uploaded = client.beta.files.upload(file=open("paper.pdf","rb"))
resp = client.messages.create(
    model="claude-sonnet-4-6",
    messages=[{"role":"user","content":[
        {"type":"document","source":{"type":"file","file_id":uploaded.id}},
        {"type":"text","text":"三句话总结这篇论文的核心结论"}
    ]}]
)
```

**工程提示**：

- 单文件 ≤ 500MB、≤ 1000 页。超过就 split + summarize map-reduce。
- Files 是**永久存储**，定期 list & delete 不用的。孤儿文件多了会被账单吓到。
- 想让 PDF 里的图片也被 Claude 看到（图表、扫描件）？直接传，不需要做 OCR。

---

## 五、工作流增强：把 Claude 嵌入你的系统

### 12. `metaprompt.ipynb` — 让 Claude 优化 Claude 的 prompt

**最小用法**：把当前 prompt + 失败样例喂给 Claude，让它重写。

```python
# 输入：当前 prompt + 10 个 bad case + 期望行为
# 输出：改进版 prompt
```

**工程提示**：

- metaprompt 的输出不要直接上线，必须**人工 + 评测回归**两道闸。
- 把 metaprompt 跑成定时任务（每周一次），是 prompt 长期不退化的关键机制。

### 13. `read_web_pages_with_haiku.ipynb` — 便宜模型干脏活

**最小用法**：抓网页 → Haiku 提取关键字段 → Sonnet 做总结。

```python
html = requests.get(url).text[:50_000]   # 先截断
extract = client.messages.create(
    model="claude-haiku-4-5",
    messages=[{"role":"user","content":
        f"从下面 HTML 提取标题、作者、发布时间、价格（JSON）：\n{html}"}]
).content[0].text
summary = client.messages.create(
    model="claude-sonnet-4-6",
    messages=[{"role":"user","content":f"基于这条数据写摘要：{extract}"}]
).content[0].text
```

**工程提示**：

- Haiku 提取结构化字段准确率已经够用，成本只有 Sonnet 的 1/15。
- 一定要**先截断 HTML**（50K 字符内），否则 token 烧在噪声上。

### 14. `how_to_make_sql_queries.ipynb` — 自然语言 → SQL 的 tool_use 范式

**最小用法**：注册 `execute_sql` 工具，schema 作为工具描述的一部分。

```python
tools = [{
    "name": "execute_sql",
    "description": "Run a read-only SQL query against the analytics DB. Tables: users(id,email,created_at), orders(id,user_id,amount,created_at)",
    "input_schema": {"type":"object",
        "properties":{"query":{"type":"string"}},
        "required":["query"]}
}]
# Claude 会生成 SELECT，由你的服务去执行并把结果回灌
```

**工程提示**：

- **绝对不要**让 Claude 直接拼 SQL 字符串给生产 DB 跑。在你服务端校验 schema、强制只读、强制 LIMIT。
- schema 别全贴 — 几百张表直接让 prompt 爆炸。给 Claude 一个 `list_tables()` 工具，让它先问再查（[anthropic/courses Tool Use](https://github.com/anthropics/courses) 推荐模式）。

---

## 六、最小落地清单

按项目阶段挑优先级，**不要全上**：

| 阶段 | 优先加入 | 理由 |
|---|---|---|
| 第一个 demo | #4 JSON mode、#11 PDF | 不被输出格式卡住 |
| 100 个用户 | #1 prompt caching、#13 Haiku 预处理 | 成本立刻砍一半 |
| 1000 个用户 | #3 batch、#7 evals、#9 moderation | 性能 + 质量 + 安全 |
| 10000 个用户 | #2 speculative cache、#10 memory compaction、#8 test cases | 体验 + 可观测 |
| 长期迭代 | #12 metaprompt、#5 citations、#6 long output | prompt 持续进化 |

## 结语

这 14 个 notebook 单独看都不复杂，但**工程价值在于组合**：caching + JSON mode + eval 是最小可用闭环；batch + memory compaction + Haiku 预处理是规模化必经之路。建议每个模型工程师至少在第一个月把 1、4、7、9 跑通 — 它们覆盖了 80% 的「线上第一次出事」。

参考资料：

- 仓库：[anthropics/claude-cookbooks](https://github.com/anthropics/claude-cookbooks/tree/main/misc)
- 课程：[anthropics/courses](https://github.com/anthropics/courses)
- 文档：[docs.claude.com](https://docs.claude.com)