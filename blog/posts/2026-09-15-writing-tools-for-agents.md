---
title: 给 Agent 写 Tools 的 6 个工程原则：从 Function Call 到 Agent Ergonomics
date: 2026-09-15
tags: [Claude, AI 工程, Tool Use, MCP]
summary: 把 Anthropic Writing Tools for Agents 文章拆成 6 个工程原则：Tool 是 deterministic + non-deterministic 系统之间的契约、Prototype → Eval → Iterate 循环、用 Claude Code 自己改 Tools、Consolidate 工具（schedule_event > list_users + create_event）、Namespacing 按 service/resource、返回 meaningful context、token-efficient 响应、prompt-engineering tool description。配具体例子 + 面试可讲的设计取舍。
source-url: https://www.anthropic.com/engineering/writing-tools-for-agents
source-title: Writing tools for AI agents — with AI agents
source-author: Ken Aizawa (Anthropic)
---

## 引子

当 LLM Agent 通过 MCP 接 100+ 工具，**Tool 设计从"function 写给程序员"变成"tool 写给 LLM"**——Anthropic 这篇的核心论点是**"Tool 是 deterministic 系统和 non-deterministic agent 之间的契约"**，**给 agent 用的 ergonomics 准则和给程序员用的 API design 完全不同**。**Sonnet 3.5 在 SWE-bench Verified 上的 SOTA 不是模型升级，是 tool description 优化**——**tool 描述的微小改动能带来戏剧性 accuracy 提升**。

下面拆 6 个工程原则，按"**思维转换 → 设计循环 → 工具选型 → 命名空间 → 返回值 → 描述工程**"递进。

---

## 1. 思维转换：Tool 是确定性 ↔ 非确定性之间的契约

**一行定位**：**Function 给 deterministic caller 用，Tool 给 non-deterministic agent 用**——**设计哲学不同**。

**核心差异**：

| 维度 | Function（给程序员） | Tool（给 agent） |
|---|---|---|
| Caller | 程序员（精确知道何时调用） | Agent（用自然语言决策） |
| 失败模式 | exception + retry | 模型 hallucinate 参数 / 调错 tool / 漏调 |
| 文档 | API doc（人类读） | Tool description + schema（LLM 读） |
| Ergonomics | 类型安全、IDE 提示 | description 清晰、example 充分 |
| 边界 | 函数签名 = 边界 | description + 触发条件 + few-shot = 边界 |

**Anthropic 的洞察**：
> "Tools that are most ergonomic for agents also end up being surprisingly intuitive to grasp as humans."

**对人类 ergonomic 的 tool 对 agent 也 ergonomic**——因为 **LLM 训练数据是人类的文字**。

**面试可讲的角度**：这是 *developer experience (DX) for AI*——**传统 DX 是 IDE + autocomplete，AI DX 是 description + schema + few-shot**。**tool description 就是 agent 的 onboarding doc**。

**工程落地 checklist**：
- ☐ 写 tool 时**假设 caller 是个新人**——description 写得像 onboarding
- ☐ **不用假设 caller 看 API doc**——所有约定必须显式写在 description
- ☐ **例子比规则有用**——few-shot > rule list

---

## 2. Prototype → Eval → Iterate 三段循环

**一行定位**：**tool 设计不是一次性写完**——**prototype 起步、eval-driven 迭代、用 Claude Code 帮你改 tool**。

**Anthropic 的工作流**：

### Step 1: Prototype
- 起 quick prototype——**Claude Code 写（甚至 one-shot）**。
- 给 Claude doc / SDK / API reference（含 `llms.txt`）。
- 包成 MCP server / DXT，本地跑起来。

### Step 2: Eval
- 生成**几十个 evaluation task**——**real-world use cases**，**real data**，**别 sandbox**。
- **Strong task 示例**：
  - "Schedule a meeting with Jane next week to discuss Acme Corp. Attach last meeting notes + reserve a conference room."（多 step + 多 tool）
  - "Customer 9182 reported triple charge. Find log + check other affected customers."
  - "Sarah Chen canceled. Prepare retention offer: (1) why leaving, (2) compelling offer, (3) risk factors."
- **Weak task 反例**：
  - "Schedule meeting with jane@acme.corp next week"（单 tool + 单一目标）
- **每个 task 配 verifiable response**——verifier 严格但不过度 strict（reject 正确的 alternative phrasing 就过严）。
- **跑 eval**——programmatic agentic loop（`while` 循环 LLM API + tool call），**每 task 一次**。

### Step 3: Iterate with Claude
- **让 Claude 自己分析 transcript**——concatenate eval transcripts → paste 进 Claude Code。
- Claude 找问题："工具描述矛盾"、"参数错误频繁"、"transcript 漏 call" 等。
- **Sonnet 3.5 的 SWE-bench Verified SOTA 不是模型升级——是 tool description 优化**。

**面试可讲的角度**：这是 *eval-driven development* for tool design——**没有 eval 改 tool = 瞎调**。**Eval 是 tool design 的 unit test**。

**工程落地**：
- ☐ **Tool 设计必须有 eval suite**——不是看 demo 觉得 OK 就上
- ☐ **Eval task 来自真实使用**——别用 synthetic toy
- ☐ **多 step task**——单 step 测不出 tool 协同
- ☐ **让 Claude 自己分析 transcript**——**它的 systematic review 比人工细**

---

## 3. 工具选型：Consolidate over Decompose

**一行定位**：**别把工作流拆成 list + create + update**——**做一个 `schedule_event` 直接完成 availability check + 创建**。

**Anthropic 的反模式 → 正解**：

| 反模式（拆碎） | 正解（Consolidate） |
|---|---|
| `list_users` + `list_events` + `create_event` | `schedule_event`（找 availability + 创建） |
| `read_logs` | `search_logs`（返回 relevant 行 + 周边 context） |
| `get_customer_by_id` + `list_transactions` + `list_notes` | `get_customer_context`（一次性返回相关 customer context） |

**核心论点**：**Tool 应该模拟人类解决问题的方式**——而不是暴露 underlying API。
- 人类不会"先 list contact、再读每个 contact 看是不是 Jane"——**会直接 search**。
- LLM agent 也不该被强迫 list-then-read 的循环——**brute force 浪费 context**。

**反面案例**：

> "If an LLM agent uses a tool that returns ALL contacts and then has to read through each one token-by-token, it's wasting its limited context space on irrelevant information (imagine searching for a contact in your address book by reading each page from top-to-bottom—that is, via brute-force search)."

**面试可讲的角度**：这是 *API design philosophy* 的代际转换——**REST 是"暴露资源 + CRUD"，Agent ergonomics 是"暴露意图 + composite action"**。**tool 是动词，不是名词**。

**工程落地 checklist**：
- ☐ 问"这个 tool 是不是 underlying API endpoint 的 1:1 wrap"——**如果是，重新设计**
- ☐ 合并"经常一起调"的 tool
- ☐ Tool 实现可以是多个 API call——**对外只暴露一个意图**
- ☐ Tool description 写"解决的问题"而不是"调用的 endpoint"

---

## 4. Namespacing：按 service + resource 分组

**一行定位**：**100 个 tool 没 namespace 是灾难**——**`asana_search` 比 `search` 让 agent 更不迷茫**。

**Anthropic 的命名策略**：
- **按 service**：`asana_search`, `jira_search`（prefix 或 suffix）
- **按 resource**：`asana_projects_search`, `asana_users_search`（多段 namespace）
- **Prefix vs suffix 的选择要看 LLM eval**——**不同 LLM 对位置敏感度不同**，**必须跑 eval 决定**。

**核心论点**：**Tool 命名是 agent 决策的 first signal**——名字 ambiguous → agent 选错。

**Anthropic 的发现**：他们**prefix vs suffix namespace 的 eval 结果 non-trivial**——**Claude 在 prefix 上表现更好，其他模型可能反过来**。**必须按你的 LLM 测**。

**面试可讲的角度**：这是 *namespace as type system*——**传统 OOP 用 namespace 做封装，LLM agent 用 namespace 做 choice signal**。**好的命名 = 好的 type**。

**工程落地**：
- ☐ **所有 tool 必须有 namespace**——不要裸名 `search`
- ☐ **Service-level prefix + resource-level suffix**——`asana_projects_search`
- ☐ **Eval 测 prefix vs suffix**——**不同模型偏好不同**
- ☐ **避免 `get_*` 这种 ambiguous 名**——`get_xxx_by_id` 更具体

---

## 5. 返回 Meaningful Context：自然语言 ID > UUID

**一行定位**：**别返回 `uuid: "a3f8c2d1"`**——**返回 `name: "Acme Corp"` + `id: 12345`**——**model 对自然语言 recall 远好于 UUID**。

**Anthropic 的发现**：
- UUID → model hallucinate / 错过 50%+。
- 自然语言名 / 0-indexed ID → precision 提升一个数量级。
- **UUID 用于后续 tool call**（必须保留）——但**不应该是 primary representation**。

**ResponseFormat 模式**：让 agent 选 detailed vs concise：

```typescript
enum ResponseFormat {
  DETAILED = "detailed",   // 含 ID、metadata、full content
  CONCISE = "concise"      // 只返回 user-facing content，省 token
}
```

**Example：Slack thread**
- DETAILED：含 `thread_ts`、`channel_id`、`user_id` ——206 tokens
- CONCISE：只返回 thread content ——72 tokens
- **节省 ⅔ token + Agent 不需要 ID 时不付出 cost**

**Response 格式选择**：
- XML / JSON / Markdown —— **不同 LLM 偏好不同**——**next-token prediction 训练数据决定**。
- 必须 eval 决定。

**面试可讲的角度**：这是 *information architecture for LLMs*——**不是所有 caller 都用所有字段**。**类比 GraphQL**——"选择你要的 fields"。

**工程落地**：
- ☐ **默认 response 只返 user-facing data**——name / title / content
- ☐ **Detailed mode 显式 opt-in**——`response_format="detailed"`
- ☐ **UUID 等技术 ID 不主动暴露**——除非 caller 明确要后续 call
- ☐ **Eval 测 response format**——XML / JSON / Markdown 哪个 model 处理最好

---

## 6. Token Efficiency + 描述工程

**一行定位**：**Tool response 默认 25K token cap（Claude Code 实测值）**——**pagination + filtering + truncation 是 must-have**。

**Token efficiency 策略**：
- **Pagination**（分页）
- **Range selection**（时间窗 / ID range）
- **Filtering**（pre-aggregate）
- **Truncation**（截断 + 提示）
- **Sensible defaults**（page size 50 / time range last 7 days）

**Claude Code 实测**：tool response **默认上限 25K token**。**预计 effective context 还会涨，但 token-efficient tool 设计不会过时**。

**Truncation 的工程细节**：
- 截断响应时**给 agent 提示**："用 narrow query / pagination / filter"。
- 错误响应**写 actionable 改进建议**——不是 opaque traceback。

**Unhelpful vs Helpful error 对比**：

```python
# ❌ Unhelpful
{"error": "InternalServerError", "trace_id": "abc-123"}

# ✅ Helpful  
{"error": "InvalidParameter",
 "message": "user_id must be a string, not integer",
 "example": "user_id='jane@acme.com'",
 "fix": "Pass user_id as string, not integer"}
```

**Description prompt engineering**（最大的杠杆）：

> "Sonnet 3.5 achieved state-of-the-art performance on SWE-bench Verified after we made precise refinements to tool descriptions, dramatically reducing error rates."

**关键洞察**：**Tool description 是 LLM context 的部分**——**改 description = 改 prompt**。

**写好 description 的技巧**：
- **像跟新员工讲**——把 implicit context（specialized query formats、niche terminology、resource relationships）**写 explicit**。
- **参数名 unambiguous**——`user_id` 不是 `user`，`thread_id` 不是 `id`。
- **Few-shot examples**——schema 表达不出的用 example（见 advanced-tool-use）。
- **强约束 schema**——`enum` 限制，不信 prompt 引导。

**面试可讲的角度**：这是 *prompt engineering applied to tool design*——**tool description 是 LLM 读的最频繁的 prompt**。**改 description 的 ROI 比改 model 大**。

**工程落地**：
- ☐ **每个 tool 配 sensible default params**（page_size / time_range / limit）
- ☐ **Error response 必须 actionable**——给例子 + 修复建议
- ☐ **Description 像 onboarding 新员工**——写 implicit context、specialized 术语
- ☐ **参数名 unambiguous**——`user_id` / `order_id` / `thread_id`，**never just `id`**
- ☐ **Eval 测 description**——**微小改动带来巨大 accuracy 提升**

---

## 一句话总结

给 Agent 写 Tool 是**"从 API 设计到 agent ergonomics"的思维转换**——**Tool 是 deterministic 与 non-deterministic 系统的契约**，**ergonomic 准则和传统 API 不同**。**Prototype → Eval → Iterate、用 Claude Code 自己改 tool、Consolidate 而非 Decompose、按 service/resource namespace、返回 meaningful context（自然语言 ID > UUID）、description 当 prompt 来精炼**。**Sonnet 3.5 在 SWE-bench 的 SOTA 不是模型升级——是 tool description 优化**。**好的 tool 设计 = 改 description 比改 model 更有效**。

## 配套阅读

- **同主题**：advanced-tool-use-three-features — Tool 层面的进阶（Search / PTC / Examples）
- **执行机制**：tool-use-engineering-patterns — Tool choice / structured output / parallel
- **评测视角**：demystifying-ai-agent-evals — Tool eval 是 Agent eval 的子集

参考资料：

- [Writing tools for AI agents — with AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents) — Ken Aizawa, Anthropic
- [Tool evaluation cookbook](https://github.com/anthropics/claude-cookbooks/tree/main/tool_evaluation) — 完整 eval pipeline
- [Claude Developer Guide — tool definitions](https://docs.claude.com/en/docs/build-with-claude/tool-use/overview) — Tool definition spec