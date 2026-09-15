---
title: Claude API 成本优化：从 prompt caching 到 model ladder 的 7 个 Pareto 工程模式
date: 2026-09-15
tags: [Claude, AI 工程, 成本优化, Pareto]
summary: 把 claude-cookbooks/cost_optimization 的 1.2MB 主教程拆成 7 个工程模式：评测基线 / prompt caching / 输入 token 管理 / agent-loop 效率 / 输出 token 管理 / Batch API / model×effort ladder。每个模式给出一行定位 + 最小代码 + 工程踩坑提示，附 Pareto 选型表与"哪类任务该用哪类杠杆"对照。
source-url: https://github.com/anthropics/claude-cookbooks/tree/main/cost_optimization
source-title: claude-cookbooks / cost_optimization
source-author: Anthropic Applied AI Team
---

## 引子

`cost_optimization/cost_optimization.ipynb` 是 Anthropic Applied AI 团队给客户的**成本审计清单**——用一个真实业务场景（保险公司索赔定损 Agent）跑完 7 个优化策略，每个策略都在 10 条人工标注的索赔上做**`pass rate × cost per task`**的 Pareto 比较。最终从 baseline $0.29/task → 优化后 **$0.03/task**（90% 节省），且**不掉准确率**。

这篇文章把它拆成 7 个工程模式，按 **"先看准 → 不动智能天花板 → 改架构"** 的顺序排列——核心论点：**模型降级是最后的杠杆**，先用 caching / batching / context engineering 把"花出去的 token"压下来，最后才换便宜模型。每个模式一行定位 + 最小代码 + 工程踩坑提示。

---

## 1. 先看准：建评测 + 跑 baseline

**一行定位**：所有优化动作之前，先建一个**冻结的评测集 + 双指标（pass rate × cost）**，没有这一步后面所有"省了 30%"都是自欺欺人。

**最小代码**：

```python
PRICING = {
    "claude-opus-4-8":    {"in": 5.00, "out": 25.00},
    "claude-sonnet-4-6":  {"in": 2.00, "out": 10.00},
    "claude-haiku-4-5":   {"in": 1.00, "out":  5.00},
}

def usage_cost(usage, model=MODEL, batch=False):
    p = PRICING[model]; m = 1_000_000
    cc = getattr(usage, "cache_creation", None)
    w5m = getattr(cc, "ephemeral_5m_input_tokens", 0) or 0
    w1h = getattr(cc, "ephemeral_1h_input_tokens", 0) or 0
    if not (w5m or w1h):
        w5m = usage.cache_creation_input_tokens or 0
    cost = (
        (usage.input_tokens or 0) * p["in"] / m
        + w5m * p["in"] * 1.25 / m              # 5min cache 写入 × 1.25
        + w1h * p["in"] * 2.00 / m              # 1h  cache 写入 × 2
        + (usage.cache_read_input_tokens or 0) * p["in"] * 0.10 / m   # cache 读 × 0.1
        + (usage.output_tokens or 0) * p["out"] / m
    )
    return cost * (0.5 if batch else 1.0)      # Batch API 5 折

# 评测：跑 10 条索赔，看 pass rate + cost/task + turns
EVAL_CLAIMS = [...]  # 10 条人工标注
def run_eval(adjudicate_fn, label, trial=1):
    correct, total_cost, total_turns = 0, 0.0, 0
    for c in EVAL_CLAIMS:
        verdict, cost, n = adjudicate_fn(c)
        if verdict == c["expected"]: correct += 1
        total_cost += cost; total_turns += n
    return {"pass_rate": correct/len(EVAL_CLAIMS),
            "per_task": total_cost/len(EVAL_CLAIMS),
            "turns": total_turns/len(EVAL_CLAIMS)}
```

**工程提示**：

- **成本单位是"per task" 不是 "per token"**。贵的模型如果少两轮，可能比便宜的更省钱。Cookbook 的核心 KPI 就是 **$/task**，每条评估样本一个数。
- **同一配置至少跑 2 次**。Agent 输出非确定性——单次跑出来的 pass rate 误差可能 ±15%。Cookbook 全部配置跑 2 trial 取均值。
- **建立质量基线后冻结它**。后续所有优化不能低于这个 pass rate——**优化降本是 OK 的，优化降智不是**。

---

## 2. Prompt Caching：auto cache → explicit breakpoint

**一行定位**：把**不变的 prefix**（system prompt + tool schema）缓存到服务端，重复利用——首调用 1.25× 写入，**后续 5min/0.1×** 读取。

**最小代码**：

```python
# 最简单：top-level auto cache（一行启用）
r = client.messages.create(
    model=MODEL, max_tokens=4096, system=SYSTEM_PROMPT, tools=TOOLS,
    messages=messages,
    cache_control={"type": "ephemeral"},   # 服务端自动放 breakpoint
)
print(f"cache_w={r.usage.cache_creation_input_tokens}, "
      f"cache_r={r.usage.cache_read_input_tokens}")

# 进阶：显式 breakpoint + 多层 prefix（不同 TTL）
r = client.messages.create(
    model=MODEL, max_tokens=4096,
    system=[
        {"type": "text", "text": POLICY_MANUAL,
         "cache_control": {"type": "ephemeral", "ttl": "1h"}},  # 长 TTL
        {"type": "text", "text": PER_CLAIM_INTAKE},            # 每次不同
    ],
    tools=TOOLS,
    messages=messages,
)
```

**工程提示**：

- **byte-stable 是命中前提**。**timestamp / request id / user name 出现在 prefix 里 = 永远 0 命中**。动态内容**必须移到 user turn**——Cookbook 实验：unstable → 44% 命中失败。
- **变量放前面 vs 后面差异巨大**。Cookbook 测试：动态变量在 manual 前 → 每次都 cache_write；manual 在前 → 写一次读多次，**省 54%**。
- **cache_control 只能放 4 个 breakpoint**。多于 4 层 prefix 用 auto cache（一个 breakpoint 自适应滑动）。
- **TTL 选择**：5min 写入 ×1.25、读取 ×0.1；1h 写入 ×2、读取 ×0.1。**调用间隔 >5min 用 1h**，否则用 5min（写入便宜）。
- **看 `cache_read_input_tokens` 而不是 cost**。**命中率是领先指标**——cost 是滞后结果。

---

## 3. 输入 token 管理：把"大块参考"挪出 prefix

**一行定位**：prefix 里凡是"大多数情况用不到"的内容，都该用 tool / skill / files API 推迟到真正需要时再加载——而不是预先全塞进 system。

**三个子杠杆**：

### 3.1 大文档挪到 tool 后面

```python
# 把 11K token 的 underwriting manual 从 system 挪到 read_manual 工具
TOOLS = [
    {"name": "read_manual", "description": "按章节读取 underwriting manual",
     "input_schema": {"type": "object",
                      "properties": {"section": {"type": "string",
                                                 "description": "章节号或关键词"}},
                      "required": ["section"]}},
    # ... 其它工具
]
# 90% 的索赔不需要读 manual → 平均 prefix 减 11K token
```

### 3.2 Tool search 把不常用工具 defer 掉

```python
# 当工具 schema > 10K token 时（典型 MCP server），把不常用的 defer
common_tools = [t for t in TOOLS if t["name"] in {"get_claim", "approve_claim"}]
rare_tools = [{**t, "defer_loading": True} for t in TOOLS if t["name"] not in {"get_claim", "approve_claim"}]

tool_search = {"type": "tool_search_tool_bm25_20251119", "name": "tool_search_tool_bm25"}
r = client.messages.create(model=MODEL, tools=[*common_tools, *rare_tools, tool_search], ...)
# Claude 先调 tool_search 找到目标工具，再调用——prefix 体积减半
```

### 3.3 大文件用 Files API + code execution

```python
# 5K 行的 CSV ledger 不能直接塞 context → 上传到 Files API，挂到 code execution 沙箱
file_id = client.beta.files.upload(file=open("ledger.csv", "rb")).id
resp = client.beta.messages.create(
    model=MODEL,
    tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
    messages=[{"role": "user", "content": [
        {"type": "container_upload", "file_id": file_id},   # ← 传到沙箱
        {"type": "text", "text": "用 pandas 求 P95 payout"},
    ]}],
)
# 主 context 只收到 1 行答案（"P95 = $4,237"），不是 100K token 的 CSV
```

**工程提示**：

- **tool 化的判断标准**：内容"大 + 命中率低"。manual 全在 prefix 里 90% 用不到 → 挪 tool；FAQ 全在 prefix 里 100% 都查 → 留 prefix。
- **tool search 在 < 10K schema 时是负担**——search step 的开销大于节省。**超过 50 个工具时再上**。
- **Files API + code execution 不只是省 token**——还能让 Claude 跑 numpy / pandas 处理大数据。**这是 RAG 之外另一种"大数据接入"路径**。

---

## 4. Agent-Loop 效率：context editing / compaction / subagent

**一行定位**：Agent 多轮对话里**中间结果（tool output、thinking）会无限堆积**——必须主动剪枝或拆 subagent，否则 context 越长每轮 input cost 越高。

**三个子杠杆**：

### 4.1 Context editing（服务端剪枝）

```python
# 加 context_management.edits 让 API 自动清理过时内容
r = client.beta.messages.create(
    model=MODEL, tools=TOOLS, messages=messages, betas=["context-management-2025-06-27"],
    context_management={
        "edits": [
            {"type": "clear_tool_uses_20250919"},     # 清理旧 tool_result
            {"type": "clear_thinking_20251015"},      # 清理旧 thinking 块
        ]
    },
)
# 服务端在 token 超过阈值时自动清——客户端零代码
```

### 4.2 Compaction（服务端压缩）

```python
# 不想丢信息？用 compact_20260112 把旧 turns 总结成 1 段
r = client.beta.messages.create(
    model=MODEL, tools=TOOLS, messages=messages,
    context_management={
        "edits": [{"type": "compact_20260112",
                   "instructions": "保留所有决策结论和已获取的关键数据"}]
    },
)
# 默认 trigger: 150K input token。适合 long-horizon agent（computer use / deep research）
```

### 4.3 Subagent 拆解

```python
# 独立子任务扔给 Haiku subagent，主 agent 只拿 1 行结果
async def precedents_subagent(query):
    return await client.messages.create(
        model="claude-haiku-4-5", max_tokens=256,
        messages=[{"role":"user","content":
                   f"从 precedents ledger 里找与 {query} 最相关的 3 条，返回 1 行摘要"}])

# 主 agent 不需要看到 5000 行 ledger，只看到 subagent 返回的 1 行
```

**工程提示**：

- **clear_tool_uses / clear_thinking 在 turn 数多时触发**——保留 cache（不破 prefix），但丢中间结果。**适合"决策已下、证据不必留"的场景**。
- **Compaction 保留信息、删体积**。比 clear 更适合"早期决策要回看"的场景——但**触发条件默认 150K token**，短 agent 用不上。
- **Subagent 最适合"独立子任务"**——一旦子任务结果要被主 agent 用 N 轮，**不如留在主 context 里**。判断标准：子任务输出是不是 1-2 行可消费。
- **Subagent 可以用便宜模型**——Haiku 跑事实收集 + Sonnet 跑判断，**成本差 5× 而质量不掉**。

---

## 5. 输出 token 管理：max_tokens / prompt / stop sequence

**一行定位**：**输出比输入贵 5×**（Opus 5/25 定价）——给模型更紧的生成约束，平均能省 30-50% 输出 token。

**三个子杠杆**：

```python
# 1. max_tokens：硬天花板（兜底用）
r = client.messages.create(model=MODEL, max_tokens=1024, messages=...)
# ⚠️ hit ceiling 时 stop_reason="max_tokens"——是兜底，不是日常调优工具

# 2. prompt 约束输出形状（最划算）
prompt_specific = """用恰好 3 句话总结这篇文章：
1. 第 1 句：核心方法
2. 第 2 句：实验结果
3. 第 3 句：局限性"""

# 3. stop sequence：内容感知截断
r = client.messages.create(
    model=MODEL, max_tokens=2048,
    stop_sequences=["<CANNOT_REVIEW>", "###END###"],
    messages=[{"role":"user","content":
               "如果无法处理就立刻输出 <CANNOT_REVIEW>，否则正常回答"}]
)
# 模型进入死胡同时不会被"我想我需要更深入思考..."这类话烧 token
```

**工程提示**：

- **`max_tokens` 是兜底**。设太大浪费，太小截断——Cookbook 推荐"略大于正常响应 + 头空间"。
- **prompt 形状比 stop sequence 重要**。"请用 100 字以内" + JSON schema 模板，平均节省 40% 输出 token。
- **stop sequence 适合"失败模式已知"**——例如"无法处理 → 输出 sentinel"，避免模型"试图解释失败"烧掉几千 token。
- **thinking 块是另一种输出**——extended_thinking 开启时 thinking token 也算 output。**预算控制 = thinking budget**（见 [Extended Thinking 3 模式](blog/posts/2026-09-15-extended-thinking-engineering.md)）。

---

## 6. Batch API：异步 -50%

**一行定位**：把所有**非交互、24h 内完成都 OK** 的请求扔进 batch 队列——**token 单价直接 5 折**，且能叠 caching。

**最小代码**：

```python
# 提交 batch（异步，1h 内返回）
batch = client.messages.batches.create(
    requests=[
        {"custom_id": f"triage-{cid}",
         "params": {"model": MODEL, "max_tokens": 512,
                    "messages": [{"role":"user","content": f"triage this claim: {claim}"}]}}
        for cid, claim in claims.items()
    ]
)
# batch 自动 50% 折扣，与 cache_read × 0.1 叠加 → 实际 ≈ 2 折

# 轮询结果
results = client.messages.batches.retrieve(batch.id)
for r in results.results:
    print(r.custom_id, r.result.message.content[0].text)
```

**工程提示**：

- **batch 是 single-shot（不支持多轮 tool loop）**。**只能用于"无工具调用"的单轮请求**——分类、抽取、批量生成。
- **典型用途**：夜间跑评测、批量数据标注、离线报表生成、回归测试集跑分。
- **batch 与 caching 不冲突**——batch 里 cache_read 仍是 ×0.1，叠 0.5 batch 折扣 = 实际 5% 输入价。
- **不要把 latency-critical 任务放 batch**——batch 不保证 SLA，可能 24h 跑完也可能 1h 跑完。

---

## 7. 模型选型与 effort ladder：最后才动

**一行定位**：在前面 6 步全做完后，才考虑**降模型档**或**降 effort**——这是"动智能天花板"的杠杆，留到最后。

**最小代码（model + effort ladder）**：

```python
LADDER = [
    ("opus · effort=high",   OPUS,   "high"),
    ("opus · effort=medium", OPUS,   "medium"),
    ("opus · effort=low",    OPUS,   "low"),
    ("sonnet · effort=high", SONNET, "high"),
    ("sonnet · effort=medium", SONNET, "medium"),
    ("sonnet · effort=low",  SONNET, "low"),
    ("haiku",                HAIKU,  None),     # Haiku 不支持 effort
]
for label, model, effort in LADDER:
    trials = []
    for trial in (1, 2):                        # 跑 2 次取均值（去随机性）
        run_eval(partial(adjudicate, model=model, effort=effort, cache=True),
                 label, quiet=True, trial=trial)
        trials.append(dict(run_eval.last))
    LADDER_RESULTS.append((label, trials))

# 画 Pareto frontier：横轴 $/10k tasks，纵轴 pass rate
# "每档 cost 提升都带来 pass rate 提升"才上 frontier，否则跳过
```

**进阶：Advisor tool——便宜的 driver + 贵的顾问**：

```python
# Sonnet 当 driver，遇到难的请 Opus 当顾问
advisor = {"type": "advisor_20260301", "name": "advisor", "model": OPUS}
r = client.beta.messages.create(
    model=SONNET, effort="low",            # driver 用便宜 + 低 effort
    tools=TOOLS + [advisor],               # 多一个 advisor 工具
    messages=messages,
    betas=["advisor-tool-2026-03-01"],
)
# Sonnet Low + Opus advisor ≈ Sonnet Medium 的质量，但 cost 低一档
```

**工程提示**：

- **`effort` 比换模型便宜**。Opus-low 比 Sonnet-high **便宜 60%**，而 Sonnet-high 通常不需要——**先降 effort、再降模型**。
- **Haiku 不支持 effort**。但 Haiku + Opus advisor 通常能挽回 Haiku 单独的 60% pass rate → 85%+。**适合"大多数简单、少数复杂"的 spiky workload**。
- **Advisor 的 gating signal 要设计好**。如果让 driver 自己判断"该不该问"——那 driver 没智能判断。**给一个明确的 threshold**（如"payout > $10K → 必问"、"fraud score ≥ 5 → 必问"）。
- **模型分解 vs advisor**：模型分解是"拆任务，每个 task 用合适的模型"（每个 subagent 各自独立 context）；advisor 是"一个 driver 全程跑，难的步骤再 call advisor"。**前者更便宜、后者更易接入**。
- **降模型失败的标志是"漏判"**。pass rate 掉 ≥5% 就**回退一档**——质量回退的成本远高于省下的 token。

---

## Pareto 选型表：哪个杠杆对哪类任务有效

| 你的痛点 | 优先杠杆 | 跳过条件 |
|---|---|---|
| **同样的 prefix 重复计费** | Prompt caching（auto → explicit） | Prefix 每次都变（动态内容混进 system） |
| **大参考文档在每个 prompt 里** | 挪到 tool / Files API | 每个 call 都要查大部分文档 |
| **tool schema 超过 10K token** | Tool search `defer_loading` | 工具数 < 50 |
| **大文件 / 图片 / PDF 占用 context** | Files API + code execution | 不需要 extract / compute |
| **Agent 多轮 context 不断膨胀** | Context editing → compaction → subagent | 单轮或短 agent |
| **输出太长 / 不稳定** | prompt 约束 + stop sequence + `max_tokens` 兜底 | 输出本身必须详尽 |
| **离线 / 异步 / 非实时** | Batch API（5 折） | 任何 latency-critical |
| **前面全做了还想再省** | effort ladder → model ladder → advisor tool | 已经是 baseline pass rate |

## 落地清单

| 阶段 | 动作 | 预期节省 |
|---|---|---|
| 上线前 | #1 建评测 + 跑 baseline | 量化起点 |
| 上线 1 周内 | #2 prompt caching（auto cache） | 30-50% input |
| 1 个月 | #3 输入 token 管理（大 doc / 工具 defer） | 20-40% input |
| 3 个月 | #4 agent-loop 效率（context 编辑） | 30-50% 总成本 |
| 6 个月 | #5 输出 token 管理（prompt 约束） | 20-30% output |
| 长期 | #6 Batch API + #7 模型/ effort ladder | 综合 50-90% |

## 与其它模式的关系

- **Prompt Caching 是 token_use 必备**：参考 [Tool Use 7 模式](blog/posts/2026-09-15-tool-use-engineering-patterns.md) #2 提到 "system + tools 可缓存"——本文是 caching 的深度实操。
- **Files API + code execution 与 Skills 重叠**：[Skills 6 模式](blog/posts/2026-09-15-claude-skills-engineering.md) 给"专家包"，本文给"大数据 + 计算"——**两者都把大体积内容移出主 context**。
- **Subagent 与 patterns/agents 直接相关**：[patterns/agents 6 模式](blog/posts/2026-09-15-patterns-agents-engineering.md) #6 async multi-agent 给"subagent 生命周期管理"，本文 §4.3 是"subagent 用于成本"。
- **Extended Thinking 与 effort**：本文 #7 的 `effort` 参数与 [extended_thinking](blog/posts/2026-09-15-extended-thinking-engineering.md) 的 `budget_tokens` **正交**——effort 控制"想多久"，thinking 块大小是它的实现机制。
- **RAG 的 chunking 决策 = 成本决策**：[RAG 5 模式](blog/posts/2026-09-15-rag-engineering-patterns.md) #1 提到 chunk_size 影响 recall & cost——chunk 越小、context 越短、单次 cost 越低，但召回率下降。

参考资料：

- [claude-cookbooks/cost_optimization](https://github.com/anthropics/claude-cookbooks/tree/main/cost_optimization)
- [Prompt Caching 官方文档](https://docs.claude.com/en/docs/build-with-claude/prompt-caching)
- [Context Editing 官方文档](https://docs.claude.com/en/docs/build-with-claude/context-editing)
- [Compaction 官方文档](https://docs.claude.com/en/docs/build-with-claude/compaction)
- [Batch API 官方文档](https://docs.claude.com/en/docs/build-with-claude/batch-processing)
- [Tool Search Tool 官方文档](https://docs.claude.com/en/docs/agents-and-tools/tool-use/tool-search-tool)
- 配套阅读：[Tool Use 7 模式](blog/posts/2026-09-15-tool-use-engineering-patterns.md)、[Agent 6 模式](blog/posts/2026-09-15-patterns-agents-engineering.md)
