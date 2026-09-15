---
title: Agent 模式工程化：从 Prompt Chaining 到 Async Subagent 的 6 个实战模式
date: 2026-09-15
tags: [Claude, AI 工程, Agent, Patterns]
summary: 把 Anthropic "Building Effective Agents" 论文对应的 patterns/agents 4 个 notebook 拆成 6 个工程模式：prompt chaining / parallelization / routing / orchestrator-workers / evaluator-optimizer / async multi-agent。每个模式一行定位 + 最小代码 + 2-3 条工程踩坑提示。
source-url: https://github.com/anthropics/claude-cookbooks/tree/main/patterns/agents
source-title: claude-cookbooks / patterns/agents
source-author: Anthropic (Erik Schluntz & Barry Zhang)
---

## 引子

`patterns/agents/` 对应的是 Anthropic 那篇经典论文 *Building Effective Agents*——4 个 notebook 覆盖 6 个 agent 模式：基础 3 件套（chaining / parallelization / routing）+ 高级 3 件套（orchestrator-workers / evaluator-optimizer / async multi-agent）。它的核心论点是：**绝大多数"AI Agent"需求用基础模式就够了，能用确定性 workflow 解决的不要上 LLM Agent**。

这篇文章按"**基础 → 高级 → 异步**"的阶梯拆 6 个工程模式。每个模式配一行定位 + 最小代码 + 工程踩坑提示。

---

## 第一档：基础 workflow

### 1. Prompt Chaining：拆任务 + 串行

**一行定位**：把任务拆成 N 个**有依赖**的子步骤，前一步输出喂下一步——本质是"LLM 版的 Unix pipeline"。

**最小代码**：

```python
def chain(input: str, prompts: list[str]) -> str:
    """每个 prompt 处理上一步的结果，串行执行"""
    result = input
    for i, prompt in enumerate(prompts, 1):
        result = llm_call(f"{prompt}\nInput: {result}")
    return result

# 用例：把绩效报告 → 提取数字 → 转百分比 → 排序 → 渲染 markdown 表格
data_processing_steps = [
    """提取文本中的所有数值和对应指标，每行 'value: metric'""",
    """把所有数值统一转为百分比格式""",
    """按数值大小降序排序""",
    """渲染成 markdown 表格，列：Metric | Value""",
]
chain(report, data_processing_steps)
```

**工程提示**：

- **每步输出要做 schema 校验**。串行链路里第 3 步崩了，90% 是第 2 步输出格式漂移——加个 pydantic 校验比加 try/except 更早发现问题。
- **每步温度要分桶**。提取（temperature=0）→ 排序（0）→ 渲染（0.3）。**创造性任务放在最后一步**，前面全部确定性。
- Chaining 是**确定性高 / 灵活度低**的模式：每步是写死的 prompt，组合方式是写死的顺序。**好处是可调试、可评测**——这是它优于 Agent 的地方。

---

### 2. Parallelization：多输入并行

**一行定位**：同一个 prompt 应用到 N 个**互相独立**的输入上，并发跑——本质是"LLM 版的 `multiprocessing.map`"。

**最小代码**：

```python
from concurrent.futures import ThreadPoolExecutor

def parallel(prompt: str, inputs: list[str], n_workers: int = 3) -> list[str]:
    with ThreadPoolExecutor(max_workers=n_workers) as executor:
        futures = [executor.submit(llm_call, f"{prompt}\nInput: {x}")
                   for x in inputs]
        return [f.result() for f in futures]

# 用例：同一份市场变化 → 分别分析对客户 / 员工 / 投资者 / 供应商 的影响
stakeholders = ["Customers: ...", "Employees: ...", "Investors: ...", "Suppliers: ..."]
results = parallel(
    "分析这个市场变化对 stakeholder group 的具体影响 + 建议行动",
    stakeholders, n_workers=4,
)
```

**工程提示**：

- **只用于独立输入**。A 的输出是 B 的输入 → 不要并行（用 chaining）。并行要求输入之间**没有信息依赖**。
- **并发上限 = 服务端 rate limit**。不是越大越好——Anthropic API 有 tier-based RPS，盲目开 50 worker 直接 429。**先看 tier、再调并发**。
- **加 timeout + fallback**。单个 worker 卡死不能让整批卡死——`f.result(timeout=30)` + 失败重试或降级到"未知"。

---

### 3. Routing：动态分发

**一行定位**：用一个 LLM 做"路由器"，根据输入特征选不同 prompt 路径——本质是"LLM 版的策略模式"。

**最小代码**：

```python
def route(input: str, routes: dict[str, str]) -> str:
    # 第一步：让 LLM 选路径（XML 输出便于解析）
    selector_prompt = f"""
    分析输入，从这些选项里选最合适的：{list(routes.keys())}
    <reasoning>为什么选这个</reasoning>
    <selection>选中的 team name</selection>
    Input: {input}"""
    route_response = llm_call(selector_prompt)
    route_key = extract_xml(route_response, "selection").strip().lower()

    # 第二步：用对应 specialist prompt 处理
    selected_prompt = routes[route_key]
    return llm_call(f"{selected_prompt}\nInput: {input}")

# 用例：客服工单按内容路由到 billing/technical/account/product
support_routes = {
    "billing":   "你是账单专家...",
    "technical": "你是技术支持工程师...",
    "account":   "你是账号安全专家...",
    "product":   "你是产品专家...",
}
response = route(ticket, support_routes)
```

**工程提示**：

- **路由 prompt 是单一失败点**。如果 router 选错路径，后面 specialist 再好也没用。**路由 prompt 要给"边界 case"的兜底**——"如果都不确定，选 billing"。
- **路径数 ≤ 7**。超出 7 个准确率掉得厉害（与 classification 同样的限制）。多路径场景用 **两级路由**：大类 → 小类。
- **路由结果要可审计**。把 router 选了什么、为什么，**写日志**——生产环境路由错误是排查最难的事。

---

## 第二档：高级 workflow

### 4. Orchestrator-Workers：动态分解 + 派发

**一行定位**：一个 LLM 当 orchestrator 现场拆任务，N 个 worker 并行执行——**适合"无法预先知道怎么拆"的复杂任务**。

**最小代码**：

```python
class FlexibleOrchestrator:
    def __init__(self, orchestrator_prompt, worker_prompt, model="claude-sonnet-4-6"):
        self.orchestrator_prompt = orchestrator_prompt
        self.worker_prompt = worker_prompt

    def process(self, task: str, context: dict | None = None):
        # 阶段 1：orchestrator 现场决定拆成几个子任务
        orch_response = llm_call(self.orchestrator_prompt.format(task=task, **context or {}))
        tasks = parse_xml_tasks(orch_response)   # 解析 <tasks><task>...</task></tasks>

        # 阶段 2：每个 worker 拿 (原始任务 + 自己的子任务) 并行执行
        results = []
        for t in tasks:
            worker_resp = llm_call(self.worker_prompt.format(
                original_task=task, task_type=t["type"],
                task_description=t["description"], **context or {}))
            results.append({"type": t["type"], "result": extract_xml(worker_resp, "response")})
        return {"analysis": extract_xml(orch_response, "analysis"), "worker_results": results}

# 用例：产品营销文案 → orchestrator 现场决定要 2-3 种风格 → 派发给 worker
orchestrator = FlexibleOrchestrator(ORCHESTRATOR_PROMPT, WORKER_PROMPT)
results = orchestrator.process(
    task="为这款环保水瓶写产品文案",
    context={"target_audience": "环保消费者", "key_features": ["无塑", "保温", "终身保修"]})
```

**工程提示**：

- **N+1 次 LLM 调用**（1 orchestrator + N workers），**N 不能太大**。Cookbook 推荐 2-3 个 worker——超过 5 个编排质量反而下降。
- **模型分工**：orchestrator 用 Sonnet（决策质量），worker 用 Haiku（执行成本）。**省钱 10× 而质量不掉**。
- **失败兜底要明确**。worker 返回空内容时，cookbook 用 `[Error: Worker X failed]` 占位——**比让 pipeline 崩掉更稳**。生产里换成降级到"已知答案"。

---

### 5. Evaluator-Optimizer：生成-评估循环

**一行定位**：一个 LLM 生成、一个 LLM 评估打分，未达标则把 feedback 喂回生成端再试——**适合"有明确评判标准 + LLM 反馈能改进"的场景**。

**最小代码**：

```python
def loop(task, evaluator_prompt, generator_prompt, max_iter=5):
    memory = []    # 记录所有尝试，喂给下一次生成
    thoughts, result = generate(generator_prompt, task)

    for i in range(max_iter):
        evaluation, feedback = evaluate(evaluator_prompt, result, task)
        if evaluation == "PASS":
            return result
        # 把"上次结果 + 反馈"塞给 generator，让它改进
        context = "Previous attempts:\n" + "\n".join(f"- {m}" for m in memory)
        context += f"\nFeedback: {feedback}"
        thoughts, result = generate(generator_prompt, task, context)
        memory.append(result)
    return result

# 用例：实现一个 O(1) 的 MinStack → 生成 → 评估（正确性 / 时间复杂度 / 风格）
#  → NEEDS_IMPROVEMENT → 反馈（异常处理、type hints、docstring）→ 改进 → PASS
loop(task, evaluator_prompt, generator_prompt)
```

**工程提示**：

- **两个先决条件**（论文强调）：① 有清晰可评估的标准；② LLM 自己能给出有意义的反馈。**没有这两点的任务不要用**——只会浪费 token。
- **Evaluator 和 Generator 可以不同模型**。Eval 用 Opus（评判要狠），Gen 用 Sonnet（执行要快）——**质量 + 成本的最优配比**。
- **`max_iter` 是救命参数**。生成器在某些 prompt 下永远不达标（feedback 不收敛），**3-5 次硬停**。否则一个请求烧 $5+。
- **memory 要有"压缩"机制**。超过 3 次尝试时只留 feedback 不留 result（避免 context 撑爆）。

---

## 第三档：异步编排

### 6. Async Multi-Agent：Hub + Subagent 生命周期

**一行定位**：所有 agent 共享一个 in-memory hub（消息总线），lead agent 动态 spawn / status / kill subagent——**适合"多 context 并行长任务"的规模化场景**。

**最小代码**（Hub + 异步 run_agent）：

```python
import anthropic, asyncio
from collections import defaultdict

client = anthropic.AsyncAnthropic()
MODEL = "claude-opus-4-8"

class Hub:
    """消息总线：每个 agent 一个 inbox + 一个 Event"""
    def __init__(self):
        self.inbox = defaultdict(list)
        self.event = defaultdict(asyncio.Event)

    def post(self, sender, recipients, content):
        for rid in recipients:
            self.inbox[rid].append({"from": sender, "content": content})
            self.event[rid].set()   # 唤醒等待方

    def drain(self, name):
        msgs, self.inbox[name] = self.inbox[name], []
        self.event[name] = asyncio.Event()
        return msgs

SEND_MESSAGE = {"name": "send_message", "input_schema": {
    "properties": {"recipient_ids": {"type": "array"},
                   "content": {"type": "string"}}, "required": ["recipient_ids", "content"]}}
WAIT_FOR_MESSAGE = {"name": "wait_for_message", "input_schema": {"properties": {}}}

async def run_agent(hub, name, system, first_user_turn, tools, max_turns=20):
    messages = [{"role": "user", "content": first_user_turn}]
    for _ in range(max_turns):
        resp = await client.messages.create(
            model=MODEL, max_tokens=2048, system=system,
            tools=tools, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "end_turn":
            return "".join(getattr(b, "text", "") for b in resp.content)

        results = []
        for block in resp.content:
            if block.type != "tool_use": continue
            if block.name == "send_message":
                hub.post(name, block.input["recipient_ids"], block.input["content"])
                out = "delivered"
            elif block.name == "wait_for_message":
                await asyncio.wait_for(hub.event[name].wait(), timeout=60)
                out = "woke"
            else:
                out = await extra_dispatch[block.name](block)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})

        # 关键：把 drain 出来的 inbox 附加到最后一个 tool result
        # → 下次 LLM 调用时自动收到消息，无需主动 poll
        inbox = hub.drain(name)
        if results and inbox:
            results[-1]["content"] += Hub.render(inbox)
        messages.append({"role": "user", "content": results})
```

**完整 lead（spawn → status → wait → kill）**：

```python
async def run_spawn_lead():
    hub, helpers = Hub(), {}

    async def create_subagents(block):
        names = []
        for instr in block.input.get("per_subagent_instructions") or [""]:
            h = f"helper{len(helpers)+1}"
            helpers[h] = asyncio.create_task(run_agent(
                hub, h, system=f"You are {h}.", first_user_turn=instr,
                tools=[SEND_MESSAGE, WAIT_FOR_MESSAGE]))
            names.append(h)
        return f"spawned: {', '.join(names)}"

    try:
        return await run_agent(hub, "lead", "你是 lead agent",
            "Spawn 3 个 helper 各 sleep 不同秒数后回报给你，然后 dismiss 它们",
            tools=[SEND_MESSAGE, WAIT_FOR_MESSAGE,
                   {"name": "create_subagents", "input_schema": {...}},
                   {"name": "kill_subagents", "input_schema": {...}}],
            extra_dispatch={"create_subagents": create_subagents,
                            "kill_subagents": lambda b: cancel(helpers, b.input["subagent_ids"])})
    finally:
        for t in helpers.values(): t.cancel()
```

**工程提示**：

- **Hub.inbox 永远要 drain**。否则 agent 永远不会看到别人发来的消息——Cookbook 把 drain 写在 run_agent 末尾，是把"消息到达"和"工具结果"合并，**避免 agent 需要主动 poll**。
- **subagent 数量 = 并发预算**。Cookbook 默认 `maxItems: 10`。**生产里要监控 spawn 数 × 平均时延**，否则一个 lead 把 100 个 subagent 全 spawn 出来直接 OOM。
- **kill_subagents 是必备**。任何 spawn 出去的 subagent 必须有终止路径——`try/finally` + `asyncio.gather(..., return_exceptions=True)`。生产里漏写 finally 是经典 leak。
- **lead 和 subagent 共享同一个 client / API key**。注意**rate limit 是全局共享的**，不是按 subagent 隔离。**监控 429**——并发高时 subagent 之间会互相挤占配额。

---

## 落地清单

| 场景 | 优先模式 | 解决的问题 |
|---|---|---|
| 单任务流水线 | #1 chaining | 多步转换 / 提取 |
| 多输入同处理 | #2 parallelization | 批量分析 / 评估 |
| 多入口分发 | #3 routing | 客服 / 文档分类路由 |
| 复杂任务动态拆 | #4 orchestrator-workers | 多视角内容生成 |
| 有标准可迭代 | #5 evaluator-optimizer | 代码 / 长文 / 翻译 |
| 规模化并行 | #6 async multi-agent | 多源研究 / 大规模任务 |

## 选型速查

```
你的任务是：
├─ 单输入 / 多步转换 → chaining
├─ 多输入 / 同样处理 → parallelization
├─ 多输入 / 不同处理 → routing
├─ 输入类型多样 / 拆法不固定 → orchestrator-workers
├─ 输出有明确评判标准 → evaluator-optimizer
└─ 需要并发跑多个长任务 → async multi-agent
```

**反向警告**：以下场景**不要用** agent pattern：

- 单轮 Q&A → 直接 `messages.create`
- 简单分类 → `tool_choice={"type": "tool"}` + 单 schema
- 数据查询 → RAG（[RAG 5 模式](blog/posts/2026-09-15-rag-engineering-patterns.md)）
- 多步但步骤固定 → **写死 Python 函数**比 agent 更可靠

## 与其它模式的关系

- **vs Tool Use**：Tool Use 是"调单个工具"，Agent pattern 是"组织多个工具调用"。Chaining / parallelization / routing 本质都是 tool_use 编排模式。
- **vs Agent SDK**：[Claude Agent SDK](blog/posts/2026-09-15-claude-agent-sdk-engineering.md) 给的是"开箱即用的 Agent 框架"，这里给的是"模式语言"。**SDK 内部实现就是这 6 个 pattern**。
- **vs Skills**：[Skills](blog/posts/2026-09-15-claude-skills-engineering.md) 是"装专业能力"，patterns 是"编排方式"。**两者正交**——一个 subagent 可以挂一个 skill。
- **vs Extended Thinking**：Evaluator-Optimizer 适合**多轮迭代优化**的场景，**单步复杂任务**用 extended_thinking 更划算。

参考资料：

- [patterns/agents 目录](https://github.com/anthropics/claude-cookbooks/tree/main/patterns/agents)
- [Building Effective Agents 论文](https://anthropic.com/research/building-effective-agents)
- 配套阅读：[Claude Agent SDK 5 模式](blog/posts/2026-09-15-claude-agent-sdk-engineering.md)、[Tool Use 7 模式](blog/posts/2026-09-15-tool-use-engineering-patterns.md)
