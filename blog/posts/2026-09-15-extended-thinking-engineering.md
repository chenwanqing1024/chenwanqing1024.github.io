---
title: Extended Thinking 实战：把 Sonnet/Opus 的深度推理变成工程能力
date: 2026-09-15
tags: [Claude, AI 工程, Reasoning]
summary: 把 claude-cookbooks/extended_thinking 的 2 个 notebook 拆成 3 个工程模式：基础启用与 budget 调参 / thinking 与 tool_use 交错 / signature 续接与 streaming。每条给最小代码 + 工程踩坑提示，对齐 anthropic-sdk-python 当前接口。
source-url: https://github.com/anthropics/claude-cookbooks/tree/main/extended_thinking
source-title: claude-cookbooks / extended_thinking
source-author: Anthropic
---

## 引子

`extended_thinking/` 目录只有 2 个 notebook，但它处理的是 Claude 模型能力变化最大的一个方向：**让模型在回答前先花 token 想清楚**。Sonnet 4.5+ 和 Opus 4.7+ 引入了"interleaved thinking"——思考和工具调用可以多轮交错，而不是想完再调。

这篇文章把目录里的两个 notebook 拆成 3 个相互独立的工程模式，按"**启用 → 交错 → 续接**"递进排列。所有代码基于 `anthropic-sdk-python` 当前接口。

---

## 1. 基础启用：`extended_thinking.ipynb`

**一行定位**：开启深度思考模式，给模型一个 `budget_tokens` 配额。

**最小代码**：

```python
resp = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=16_000,
    thinking={
        "type": "enabled",
        "budget_tokens": 8_000,   # ← 思考配额，必须 ≥1024 且 < max_tokens
    },
    messages=[{"role": "user", "content":
        "给我一个 30 天从 JVM 后端转 AI 工程师的学习路线"}]
)

# 响应里包含两类块
for blk in resp.content:
    if blk.type == "thinking":
        print(f"[thinking {len(blk.thinking)} chars] {blk.thinking[:200]}...")
    elif blk.type == "text":
        print(f"[answer] {blk.text}")
```

**工程提示**：

- **不是所有任务都该开 thinking**。简单分类、JSON 抽取、FAQ 回答——开了反而拖慢 + 烧钱。判断准则：
  - ✅ 开：多步推理、复杂代码 debug、长规划、策略博弈、数学/逻辑题
  - ❌ 关：格式化抽取、单轮 Q&A、tool call 编排（除非用交错模式，见 §2）
- `budget_tokens` 不是越大越好。**经验值**：复杂代码规划 4000-8000；多步骤业务决策 8000-16000；超过 16000 通常是 prompt 设计有问题，不是 thinking 不够。
- `display: "omitted"` 可以让 thinking 块不返回原文（节省下游 token），但**保留 signature** 用于多轮续接。

---

## 2. Thinking 与 Tool Use 交错：`extended_thinking_with_tool_use.ipynb`

**一行定位**：让模型**思考 → 调工具 → 看结果 → 再思考 → 再调工具**，而不是"想完再动"。

**最小代码**：

```python
tools = [{
    "name": "query_db",
    "description": "Run a read-only SQL query, returns rows as JSON.",
    "input_schema": {"type": "object",
                     "properties": {"sql": {"type": "string"}},
                     "required": ["sql"]}
}]

def agent_loop(user_query: str, max_iters: int = 10):
    messages = [{"role": "user", "content": user_query}]
    for i in range(max_iters):
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16_000,
            thinking={"type": "enabled", "budget_tokens": 4_000},
            tools=tools,
            messages=messages,    # ← 每轮都把上一轮 thinking + tool_use 完整回灌
        )
        # 把整段 content（thinking + tool_use）追加进消息
        messages.append({"role": "assistant", "content": resp.content})

        # 如果有 tool_use 就执行，否则结束
        tool_uses = [b for b in resp.content if b.type == "tool_use"]
        if not tool_uses:
            return next(b.text for b in resp.content if b.type == "text")

        # 执行并回灌 tool_result
        results = []
        for tu in tool_uses:
            rows = db.execute(tu.input["sql"])
            results.append({"type": "tool_result", "tool_use_id": tu.id,
                            "content": json.dumps(rows)})
        messages.append({"role": "user", "content": results})
```

**工程提示**：

- **交错是 Agent 推理质量的关键**。非交错 Agent（先想完再调）有个常见 bug：模型想好"应该查订单表"，结果调错了表，**因为它没看到 schema 就开始思考了**。交错模式下，模型在收到表结构后再调整后续思考。
- 每轮 thinking 配额要**递减**：第一轮 4000（探索），后续 1500-2000（细化）。否则一个 Agent 跑 10 轮光 thinking 就烧 4 万 token。
- `max_iters` 是救命参数——Agent 死循环（重复调同一个工具）在生产里是真实事故。

---

## 3. Signature 续接与流式：`extended_thinking.ipynb` + signature API

**一行定位**：把 thinking 块的 `signature` 当成模型"思考状态的指纹"回传，保持多轮思考连续性。

**最小代码（多轮续接）**：

```python
# 第一轮
resp1 = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=8_000,
    thinking={"type": "enabled", "budget_tokens": 4_000},
    messages=[{"role": "user", "content": "设计一个支持 100k QPS 的推荐系统"}],
)

# 第二轮：必须把第一轮 thinking + 文本完整回灌
# 注意：thinking 块必须原封不动（包括 signature 字段）
resp2 = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=8_000,
    thinking={"type": "enabled", "budget_tokens": 4_000},
    messages=[
        {"role": "user", "content": "设计一个支持 100k QPS 的推荐系统"},
        {"role": "assistant", "content": resp1.content},   # ← 含 thinking 块 + signature
        {"role": "user", "content": "在线部分用 Flink 还是 Kafka Streams？"},
    ],
)
```

**最小代码（流式 + thinking 跳过显示）**：

```python
with client.messages.stream(
    model="claude-sonnet-4-6",
    max_tokens=8_000,
    thinking={"type": "enabled", "budget_tokens": 4_000, "display": "omitted"},
    messages=[...],
) as stream:
    for event in stream:
        if event.type == "content_block_start":
            if event.content_block.type == "thinking":
                print("[thinking...]", end="", flush=True)
            elif event.content_block.type == "text":
                print("\n[answer] ", end="", flush=True)
        elif event.type == "content_block_delta":
            if event.delta.type == "text_delta":
                print(event.delta.text, end="", flush=True)
```

**工程提示**：

- **`signature` 是 thinking 块的身份凭据**，改一个字就 400 报错。生产代码里**永远不要**手动构造 thinking 块——直接 `messages.append({"role":"assistant", "content": prev_resp.content})` 整段回灌。
- 想省下游 token：服务端开 `display: "omitted"`，客户端拿到的是 thinking 块**只有 signature + 空 thinking 字段**——不显示原文但仍可续接。
- 流式场景：thinking 块和 text 块是分开发的 `content_block_start` 事件，前端可以折叠 / 隐藏 / 实时显示。

---

## 落地清单

| 场景 | 是否启用 thinking | budget | 模式 |
|---|---|---|---|
| JSON 抽取 / 格式化 | ❌ 关 | — | — |
| 单轮 FAQ 回答 | ❌ 关 | — | — |
| 单 Agent + 工具（无思考） | ❌ 关 | — | — |
| 复杂代码生成 / debug | ✅ 开 | 4000-8000 | 单轮 |
| Agent 编排（多工具调用） | ✅ 开 | 1500-4000/轮 | 交错 |
| 长规划 / 策略博弈 | ✅ 开 | 8000-16000 | 单轮 |
| 多轮续接 / 流式 | ✅ 开 + signature | 4000 | 多轮续接 |

## 与其它模式的关系

- **tool_use 是 thinking 的脚**：`tool_use_with_pydantic` 提供结构化输出、`memory_cookbook` 提供长记忆，没有 thinking 这两者的质量会下降一个数量级。
- **tool_search 解放 thinking 配额**：工具越多、prompt 越长，thinking 配额越被稀释——把工具移出主 context（用 tool_search）能腾出 thinking 空间。
- **extended_thinking 与 prompt caching 互不冲突**：thinking 块本身不进缓存（每次都不同），但 system / tools 可以缓存，**两者叠加是生产 Agent 的标配**。

参考资料：

- [claude-cookbooks/extended_thinking](https://github.com/anthropics/claude-cookbooks/tree/main/extended_thinking)
- [Extended Thinking 官方文档](https://docs.claude.com/en/docs/build-with-claude/extended-thinking)
- 配套：[tool_use 7 个工程模式](blog/posts/2026-09-15-tool-use-engineering-patterns.md)