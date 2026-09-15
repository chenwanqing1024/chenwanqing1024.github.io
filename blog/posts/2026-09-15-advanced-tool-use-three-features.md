---
title: 高级 Tool Use 三大特性：Tool Search、Programmatic Calling、Tool Examples 的 5 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, Tool Use, MCP]
summary: 把 Anthropic Advanced Tool Use 工程文章拆成 5 个工程模式：Tool Search Tool 让 Claude 按需加载（节省 85% token，accuracy 从 49% → 74%）、Programmatic Tool Calling 让代码代替推理做编排（token 降 37%、accuracy 提升 5 个百分点）、Tool Use Examples 替代 schema 模糊（accuracy 从 72% → 90%）。每个模式给定位 + 代码 + 落地边界。
source-url: https://www.anthropic.com/engineering/advanced-tool-use
source-title: Advanced tool use
source-author: Bin Wu (Anthropic Claude Developer Platform)
---

## 引子

当 Agent 接 100+ 工具（GitHub / Slack / Sentry / Grafana / Jira ...），**工具定义就能吞掉 100K+ token**——剩下给真正工作的空间是零。这篇 Anthropic 的 advanced tool use 解决**三个工程难题**：(1) 工具太多 context 装不下；(2) 中间结果太多 context 装不下；(3) JSON schema 表达不出"这个参数通常怎么填"。**三个特性都是直接量化收益的**——85% token 节省、accuracy 49→74%、accuracy 72→90%。

下面拆 5 个工程模式，按"**问题 → 解法 → 量化收益 → 落地边界**"递进。

---

## 1. Tool Search Tool：让 Claude 按需加载工具定义

**一行定位**：**不要一次塞所有工具定义进 context**——给 Claude 一个 search tool，让它**自己找**它需要的工具。

**Anthropic 的量化收益**：
- 50+ MCP 工具的传统加载 = ~72K token → Tool Search Tool 后 = ~8.7K token（**85% 节省**）。
- 内部 eval：Opus 4 从 49% → 74%，Opus 4.5 从 79.5% → 88.1%。
- **Prompt caching 不破**——deferred 工具不进 initial prompt，**system prompt 和 core 工具保持 cacheable**。

**实现机制**：
- 所有工具在 API 注册，但 `defer_loading: true` 标记成"按需发现"。
- Claude 一开始只看到 Tool Search Tool 本身 + 没 deferred 的 critical 工具。
- Claude 要 GitHub 时搜 "github" → 只 `github.createPullRequest` 等被加载。

**最小用法**：

```json
{
  "tools": [
    {"type": "tool_search_tool_regex_20251119", "name": "tool_search_tool_regex"},
    {
      "name": "github.createPullRequest",
      "description": "Create a pull request",
      "input_schema": {...},
      "defer_loading": true
    }
  ]
}
```

**MCP 整 server defer**：

```json
{
  "type": "mcp_toolset",
  "mcp_server_name": "google-drive",
  "default_config": {"defer_loading": true},
  "configs": {
    "search_files": {"defer_loading": false}   // 高频工具保留即时加载
  }
}
```

**面试可讲的角度**：这是 *lazy loading* 应用到 context 管理。**传统做法把所有 jar 放进 classpath，lazy loading 只在调用时加载**——同样的工程原理。

**工程落地**：
- ☐ Tool 定义 > 10K token → 必上 Tool Search
- ☐ MCP 多 server → 整 server defer，高频工具单独 pinned
- ☐ Tool description 必须**清楚且具体**（"Search for customer orders by date range, status, or total amount" 而不是 "Execute order query"）——search 靠 name + description 匹配
- ☐ 3-5 个最常用工具保持 always loaded（避免每次都要 search）

---

## 2. Programmatic Tool Calling：让代码代替推理做编排

**一行定位**：**别让 Claude 用自然语言做循环**——让它**写 Python 脚本调工具**，**只有最终结果进 context**。

**Anthropic 的量化收益**：
- Token：从 43,588 降到 27,297（**37% 节省**）。
- Latency：20+ tool calls 一次代码块 = **消除 19+ 推理 round-trip**。
- Accuracy：knowledge retrieval 25.6% → 28.5%；GIA benchmark 46.5% → 51.2%。

**机制**：
- Claude 写 Python 在 Code Execution 沙箱里跑。
- 脚本调用工具时**暂停**，API 返回工具结果给**脚本**而不是 Claude。
- 脚本继续跑，**只有 `print()` 的 stdout 进 Claude context**。

**Budget compliance 示例**（Claude 写的代码）：

```python
team = await get_team_members("engineering")

levels = list(set(m["level"] for m in team))
budget_results = await asyncio.gather(*[
    get_budget_by_level(level) for level in levels
])
budgets = {level: budget for level, budget in zip(levels, budget_results)}

expenses = await asyncio.gather(*[
    get_expenses(m["id"], "Q3") for m in team
])

exceeded = []
for member, exp in zip(team, expenses):
    budget = budgets[member["level"]]
    total = sum(e["amount"] for e in exp)
    if total > budget["travel_limit"]:
        exceeded.append({"name": member["name"], "spent": total, "limit": budget["travel_limit"]})

print(json.dumps(exceeded))
```

**Context 收益**：2,000+ expense line items（~200KB raw data）→ 只剩 `print` 出来的 2-3 个超支人（**1KB**）。

**面试可讲的角度**：这是 *ETL vs Interactive query* 的工程类比。**传统 tool call = 交互式查询（每条 SQL 回 model 一次），PTC = ETL 脚本（一次拉数据、清洗、汇总、最后才 report）**。

**工程落地**：
- ☐ **多步骤 + 3+ dependent tool call** → 必上 PTC
- ☐ **并行独立操作**（如查 50 个 endpoint）→ PTC + `asyncio.gather`
- ☐ **filter / sort / aggregate** 中间结果 → PTC（避免污染 context）
- ☐ **大 dataset 只需 aggregate / summary** → PTC
- ☐ **工具 description 必须**清晰写明 return format——Claude 写 parsing 代码要看 schema

**Tool opt-in**：

```json
{
  "tools": [
    {"type": "code_execution_20250825", "name": "code_execution"},
    {
      "name": "get_team_members",
      "description": "Get all members of a department...",
      "input_schema": {...},
      "allowed_callers": ["code_execution_20250825"]
    }
  ]
}
```

---

## 3. Tool Use Examples：用 examples 替代 schema 模糊

**一行定位**：**JSON Schema 定义的是"语法"，Examples 定义的是"惯用法"**——后者才是真 signal。

**Anthropic 的量化收益**：复杂参数处理 accuracy 从 **72% → 90%**。

**问题**：Schema 能说"title 是 string"，但不能说：
- `due_date` 用 `"2024-11-06"`、`"Nov 6, 2024"` 还是 ISO 8601？
- `reporter.id` 是 UUID、`"USR-12345"` 还是 `"12345"`？
- 何时填 `reporter.contact`？
- `escalation.level` 和 `escalation.sla_hours` 与 priority 怎么对应？

**解法**：

```json
{
  "name": "create_ticket",
  "input_schema": { /* schema 不变 */ },
  "input_examples": [
    {
      "title": "Login page returns 500 error",
      "priority": "critical",
      "labels": ["bug", "authentication", "production"],
      "reporter": {
        "id": "USR-12345",
        "name": "Jane Smith",
        "contact": {"email": "jane@acme.com", "phone": "+1-555-0123"}
      },
      "due_date": "2024-11-06",
      "escalation": {"level": 2, "notify_manager": true, "sla_hours": 4}
    },
    {
      "title": "Add dark mode support",
      "labels": ["feature-request", "ui"],
      "reporter": {"id": "USR-67890", "name": "Alex Chen"}
    },
    {
      "title": "Update API documentation"
    }
  ]
}
```

**Claude 从三个 example 推断**：
- 日期用 `YYYY-MM-DD`，user ID 走 `USR-XXXXX`，labels 走 kebab-case。
- `reporter` 嵌套 `contact` 怎么构造。
- Critical bug = 完整 contact + escalation + SLA；feature request = reporter 不带 contact；internal task 只 title。

**面试可讲的角度**：这是 *few-shot > zero-shot* 的 schema 版本。**Examples 比 description 更能让模型学到"约定"**——约定是 schema 写不出的。

**工程落地 checklist**：
- ☐ 用**真实数据**（real city name、plausible price），不要 `"string"` / `"value"`
- ☐ 覆盖 variety：**最小 / 部分 / 完整** specification
- ☐ **1-5 个 examples per tool**——多了烧 token，少了学不到
- ☐ 只在**schema 表达不出**的地方加 example——别为 obvious parameter 加

---

## 4. 三大特性的组合策略

**Anthropic 的官方建议**：**不要一次全开**——按 bottleneck 选。

| Bottleneck | 解法 |
|---|---|
| 工具定义吞 context | Tool Search Tool |
| 中间结果污染 context | Programmatic Tool Calling |
| 参数错误 / malformed call | Tool Use Examples |

**三个特性互补不冲突**：
- Tool Search Tool 解决"找对工具"。
- Programmatic Tool Calling 解决"高效用工具"。
- Tool Use Examples 解决"用对工具"。

**面试可讲的角度**：这是 *build vs buy* 的工程决策——**三个特性像优化栈的不同层级**（cache 层、执行层、契约层）。**先找最痛的一层解决，不要全栈优化**。

**工程落地**：
- **Profile 你的 Agent**——token 用在哪？tool selection error rate 多高？parameter error 多高？
- **找最大瓶颈先解**——别三个一起上，分不清效果。
- **测完一个再加下一个**——A/B 对比，确认量化收益符合官方数据。

---

## 5. 落地决策树：用还是不用

**Anthropic 给的边界条件**：

### Tool Search Tool 用 vs 不用
- ✅ **用**：tool def > 10K token、tool selection accuracy 低、多 MCP server、10+ tools
- ❌ **不用**：< 10 tools、所有 tools 每 session 都用、tool def 紧凑

### Programmatic Tool Calling 用 vs 不用
- ✅ **用**：处理大 dataset 只需 aggregate、多步骤 3+ dependent call、filter/sort/transform tool 结果、并行操作（50 个 endpoint）
- ❌ **不用**：单 tool invocation、Claude 必须看所有中间结果、快速小响应 lookup

### Tool Use Examples 用 vs 不用
- ✅ **用**：复杂嵌套结构、optional 参数很多、有 domain-specific convention、相似的工具（如 `create_ticket` vs `create_incident`）
- ❌ **不用**：单参数 obvious、URL / email 标准格式、validation 由 JSON Schema 处理更合适

**面试可讲的角度**：这是 *build-vs-buy* 的判断标准——**任何优化都有 setup cost 和 runtime cost**，只有 ROI > 1 才值得。

**工程落地 checklist**：
- ☐ 测 baseline（不开特性的 token + accuracy）
- ☐ 单开一个特性，跑同一 workload
- ☐ 验证 ROI > 1.5x 再继续（特性有 prompt caching 影响）
- ☐ **Prompt caching 影响**：Tool Search Tool 不破 cache，PTC 加 `code_execution` 进 tools 可能破 cache（取决于怎么写）

---

## 一句话总结

Tool use 的三个高级特性**解决三个独立 bottleneck**：**Tool Search 解决"找对工具"（节省 85% token）、PTC 解决"高效用工具"（节省 37% token + 消除推理 round-trip）、Examples 解决"用对工具"（accuracy +18 个百分点）**。**先 profile、再选特性、ROI > 1.5x 才上**——这是任何 AI 优化的通用工程法则。

## 配套阅读

- **同主题**：code-execution-with-mcp — PTC 的底层（Code Execution + MCP）
- **执行机制**：tool-use-engineering-patterns — Tool choice / structured output / parallel
- **评测视角**：demystifying-ai-agent-evals — token / accuracy 怎么量化

参考资料：

- [Advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use) — Bin Wu, Anthropic
- [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp) — PTC 的 predecessor
- [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python) — 完整示例