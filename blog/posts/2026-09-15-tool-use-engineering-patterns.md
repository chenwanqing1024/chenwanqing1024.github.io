---
title: Claude Tool Use 实战：从 tool_choice 到 tool_search 的 7 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, Tool Use, Agent]
summary: 把 claude-cookbooks/tool_use 目录拆成 7 个独立可复制的工程模式，按"单工具控制 / 多工具编排 / 规模化"三档排列。每个模式给出一行定位 + 最小代码 + 工程踩坑提示，对齐 anthropic-sdk-python 当前接口。
source-url: https://github.com/anthropics/claude-cookbooks/tree/main/tool_use
source-title: claude-cookbooks / tool_use
source-author: Anthropic
---

## 引子

`tool_use/` 是 `claude-cookbooks` 里**最大、最常被引用**的目录：14 个 notebook 覆盖 tool_choice、结构化输出、并行调用、程序化调用、工具检索、外部记忆、上下文压缩。它对应的工程问题是同一件事——**让 Claude 在生产里稳定地调用你的服务**。

这篇文章把目录里的核心 notebook 拆成 7 个相互独立的工程模式，按"**单工具控制 → 多工具编排 → 规模化**"三档排列。每个模式配一行定位 + 最小代码 + 3 条以内工程踩坑提示。所有代码基于 `anthropic-sdk-python >= 0.40` 当前接口。

---

## 第一档：单工具控制

### 1. `tool_choice.ipynb` — 三档控制：auto / any / 指定工具

**最小用法**：

```python
# auto（默认）：让 Claude 自己决定要不要调用
resp = client.messages.create(model="claude-sonnet-4-6",
                              tools=tools, messages=...)

# any：必须调至少一个工具，但不限制哪个
resp = client.messages.create(model=..., tool_choice={"type": "any"},
                              tools=tools, messages=...)

# 指定具体工具：必须调用这一个
resp = client.messages.create(model=...,
                              tool_choice={"type": "tool", "name": "search_docs"},
                              tools=tools, messages=...)
```

**工程提示**：

- 客服 / 路由 Agent 用 `any` 保证**每轮必调工具**，不会出现"我直接回答了"的退化。
- 数据抽取 / 格式化场景用「指定工具」+ JSON schema，**让 schema 替代 prompt 引导**。
- 不要混用 `tool_choice` 和自由文本——模型收到「必须调用 X」后还想「顺便聊聊」是反模式。

### 2. `extracting_structured_json.ipynb` — 用 tool_use 替代正则抓 JSON

**最小用法**：

```python
from pydantic import BaseModel, Field
from typing import Literal

class Sentiment(BaseModel):
    label: Literal["pos", "neg", "neutral"]
    score: float = Field(ge=0, le=1)

tool = {
    "name": "emit",
    "description": "Emit the sentiment result.",
    "input_schema": Sentiment.model_json_schema(),
}

resp = client.messages.create(model="claude-sonnet-4-6",
                              tools=[tool],
                              tool_choice={"type": "tool", "name": "emit"},
                              messages=[{"role":"user","content": text}])

for blk in resp.content:
    if blk.type == "tool_use" and blk.name == "emit":
        result = Sentiment.model_validate(blk.input)   # pydantic 直接校验
```

**工程提示**：

- 配合 `tool_use_with_pydantic.ipynb`：把 pydantic 模型直接喂给 `input_schema`，省去手写 schema 字段。
- 不要再写「请输出严格 JSON」——模型对 tool_use 的严格度比 prompt 引导高一个数量级，正则解析已成易碎层。
- `strict: True`（部分模型支持）开启后 schema 解析严格匹配，连 enum 之外的值都不返回。

### 3. `calculator_tool.ipynb` — 单工具的最小闭环范式

**最小用法**：

```python
# 1. 定义工具（描述要清楚，模型靠这个决定何时调）
tools = [{
    "name": "calc",
    "description": "Evaluate a Python math expression. Returns a number.",
    "input_schema": {"type": "object",
                     "properties": {"expr": {"type": "string"}},
                     "required": ["expr"]}
}]

# 2. 让 Claude 决策
resp = client.messages.create(model=..., tools=tools, messages=...)
tool_use = next(b for b in resp.content if b.type == "tool_use")

# 3. 你执行（在自己的环境里）
result = eval(tool_use.input["expr"])  # 生产环境换成安全的求值器

# 4. 把结果回灌给 Claude
final = client.messages.create(model=..., tools=tools, messages=[
    *prior_msgs,
    {"role":"assistant", "content": resp.content},
    {"role":"user", "content": [{
        "type": "tool_result", "tool_use_id": tool_use.id,
        "content": str(result)
    }]}
])
```

**工程提示**：

- **永远不要让模型生成的字符串直接进 `eval()`**。生产里用 `numexpr`、`asteval`、或 `simpleeval` 这种受限求值器；或者直接调外部计算服务（WolframAlpha / SymPy）。
- 工具的 `description` 是给模型看的——写得越具体，调用越准。把"何时用 / 何时不用 / 参数格式约定"全部写进 description 字段。
- 工具调用要有超时和重试。一次 tool call 超过 10s 没回就要降级或 fallback，否则主对话永远阻塞。

---

## 第二档：多工具编排

### 4. `parallel_tools.ipynb` — 一次返回多个工具调用

**最小用法**：在 prompt 里鼓励 Claude 一次性发多个独立工具调用。

```python
# 场景：用户问"北京和上海的天气怎么样？"
resp = client.messages.create(model=..., tools=[get_weather], messages=[
    {"role":"user","content":"北京和上海的天气怎么样？"}
])
# resp.content 会包含两个 tool_use block：location=北京、location=上海

# 并行执行
results = await asyncio.gather(*[
    execute_weather(tu.input["location"])
    for tu in resp.content if tu.type == "tool_use"
])

# 把所有结果一次性回灌（保留顺序）
tool_results = [{
    "type": "tool_result",
    "tool_use_id": tu.id,
    "content": str(res),
} for tu, res in zip(
    [b for b in resp.content if b.type == "tool_use"], results
)]

final = client.messages.create(model=..., tools=[get_weather], messages=[
    *prior_msgs,
    {"role":"assistant","content": resp.content},
    {"role":"user","content": tool_results}
])
```

**工程提示**：

- 默认 Claude 就会发多调用，但**显式鼓励**"请一次性检索所有需要的字段"可以提高并发命中率。
- 工具之间有依赖关系时（A 的输出是 B 的输入），不要用并行——让模型分两次返回。
- 并行度受你服务端的 QPS 限制。一个 Agent 同时打 5 个工具调用没问题，20+ 就要排队。

### 5. `programmatic_tool_calling_ptc.ipynb` — 在沙箱里跑代码减少 token 消耗

**最小用法**：注册一个 `code_execution` 工具，让 Claude 写 Python 来串多个工具。

```python
# 把多个工具 + 一个 code_execution 一起注册
tools = [
    {"name": "list_files", "description": "...", "input_schema": {...}},
    {"name": "read_file", "description": "...", "input_schema": {...}},
    {"name": "grep",      "description": "...", "input_schema": {...}},
    {"type": "code_execution_20250825",
     "name": "code_execution"}     # ← 沙箱代码执行
]

# Claude 不再逐个调用工具，而是写一段 Python：
#   files = list_files(path='/src')
#   matches = [read_file(path=f) for f in files if grep(pattern='TODO', path=f)]
# 只有 matches 这一份结果回到主 context。
```

**工程提示**：

- 适用场景：**大量工具调用、只需要聚合结果**——比如批量文件处理、批量 DB 查询、批量 API 拉取。
- Token 节省量级：100 个工具调用 → 主 context 只收 1 个聚合结果，省 99× 工具 description + response 的开销。
- 沙箱隔离是必须的。`code_execution_20250825` 这种内置工具自带隔离层；自己实现时用 gVisor / Firecracker / Docker，**绝不能让模型生成的 Python 跑在你主进程**。

---

## 第三档：规模化

### 6. `tool_search_with_embeddings.ipynb` — 工具太多时按需检索

**最小用法**：把不常用的工具标 `defer_loading=True`，注册一个 `tool_search` 让模型按需加载。

```python
# 常用工具直接列
common_tools = [
    {"name": "search", "description": "...", "input_schema": {...}},
    {"name": "summarize", "description": "...", "input_schema": {...}},
]

# 不常用的全部 defer
rare_tools = [
    {"name": f"action_{i}", "description": "...", "input_schema": {...},
     "defer_loading": True}
    for i in range(500)
]

# 工具搜索器（基于 BM25 或 embedding）
search_tool = {
    "type": "tool_search_tool_bm25_20251119",
    "name": "tool_search_tool_bm25"
}

resp = client.messages.create(model=..., tools=[*common_tools, *rare_tools, search_tool], ...)

# Claude 会先调 tool_search 找到 action_347，再调 action_347
# 中间过程在 Anthropic 服务端走完，回灌到主 context 的只有最终结果
```

**工程提示**：

- 工具超过 **50 个**就该上 tool_search。把常用 5-10 个常驻，其它全部 defer。
- 工具 description 写得越精确，检索越准。建议给每个工具配 1 个 input_example。
- `tool_search_alternate_approaches.ipynb` 给了对比：BM25 便宜但召回差，embedding 准但要 embedding 成本。按你的工具规模选。

### 7. `memory_cookbook.ipynb` + `memory_tool.py` — 把记忆外置

**最小用法**：用内置的 `memory_20250818` 工具，让 Claude 自己管理长期记忆文件。

```python
memory_tool = {
    "type": "memory_20250818",
    "name": "memory"
}

resp = client.messages.create(model="claude-sonnet-4-6",
                              tools=[memory_tool],
                              messages=[{"role":"user","content": "记住我下周要去上海出差"}])

# Claude 会调用 memory 工具写一个文件到 /memories
# 下次会话带上同一个 memory tool + path，Claude 自动 recall
```

**工程提示**：

- 适用**跨会话的用户偏好 / 项目记忆 / 累积事实**——客服 Agent、个人助理、长期项目追踪。
- 与 `automatic_context_compaction.ipynb` 配合：长会话里 compaction 收近期窗口，memory 存远期事实。
- **不要**把所有上下文都往 memory 里塞——memory 是给 Claude 自己查询用的，不是给你当 KV 存储。

---

## 落地清单：按 Agent 复杂度选模式

| 阶段 | 优先加入的模式 | 解决的问题 |
|---|---|---|
| 第一个工具调用 | #1 tool_choice、#2 structured JSON | 必调 / 必格式化 |
| 5-10 个工具 | #3 calculator 范式、#4 parallel | 单闭环 + 并行加速 |
| 30-50 个工具 | #2 严格 schema、#5 PTC | token 控制 + 工具描述稳定性 |
| 100+ 个工具 | #6 tool_search | 突破 schema 窗口 |
| 跨会话 | #7 memory | 用户偏好 / 项目状态持久化 |
| 长会话 | `automatic_context_compaction.ipynb`（同目录） | token 窗口控制 |

## 结语

tool_use 不是"加了 tools 就完事"——它是一组可叠加的模式。`tool_choice` 控制必调性，`parallel` 拉并发，PTC 把 N 次调用压成 1 份结果，`tool_search` 把"工具描述"从主 context 移出去，`memory` 把"历史"从主 context 移出去。**你做的每一个 Agent 优化，本质上都是在做一件事：让 Claude 在每一轮对话里看到的 token 尽量少而准**。

参考资料：

- [anthropics/claude-cookbooks/tree/main/tool_use](https://github.com/anthropics/claude-cookbooks/tree/main/tool_use)
- [docs.claude.com Tool Use 指南](https://docs.claude.com/en/docs/tool-use/overview)