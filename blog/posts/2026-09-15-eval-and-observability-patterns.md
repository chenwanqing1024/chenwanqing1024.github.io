---
title: 评测与可观测：从 Usage 监控到 Agent 基准复现的 6 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, Evals, Observability]
summary: 把 claude-cookbooks 里 observability / tool_evaluation / evals / third_party 4 个目录合并成 6 个工程模式：Usage & Cost Admin API 监控 / Tool Evaluation XML 框架 / Agentic Search harness / Programmatic Tool Calling 杠杆 / Model-as-Judge F1 评分 / 第三方生态地图。每个模式一行定位 + 最小代码 + 2-3 条工程踩坑提示。
source-url: https://github.com/anthropics/claude-cookbooks/tree/main/{observability,tool_evaluation,evals,third_party}
source-title: claude-cookbooks / observability + tool_evaluation + evals + third_party
source-author: Anthropic
---

## 引子

claude-cookbooks 里和"评测 + 可观测"相关的目录有 4 个：

| 目录 | 解决的问题 |
|---|---|
| `observability/` | 怎么从 Admin API 拉 token / cost 数据 |
| `tool_evaluation/` | 怎么评测一组 tool definition 的可用性 |
| `evals/` | 怎么跑 agentic search 基准（DeepSearchQA / BrowseComp） |
| `third_party/` | 第三方集成（LlamaIndex / Pinecone / MongoDB 等）的样板 |

它们的共同主题：**怎么"度量 + 监控"一个 Claude 应用**——这是 AI 工程和传统软件工程最不一样的地方。传统软件上线后看 latency / error rate，AI 应用上线后还要看 **模型评测分数 + token 成本 + 缓存命中率 + 工具调用成功率**。这 4 个目录把"Anthropic 怎么度量自己的产品"和"开发者怎么度量自己的应用"都说清楚了。

这篇文章把它们合并成 6 个相互独立的工程模式，按"**观测 → 单任务评测 → 长链路基准 → 评分 → 生态**"排列。每个模式配一行定位 + 最小代码 + 2-3 条工程踩坑提示。

---

## 1. Usage & Cost Admin API：拉 token / cost 数据

**一行定位**：用 `sk-ant-admin...` Admin Key 调 `usage_report/messages` 和 `cost_report` 两个端点，把 token 消耗和 USD 成本拿到本地做监控。

**最小代码**：

```python
import os, requests
from datetime import datetime, time, timedelta

class AnthropicAdminAPI:
    BASE = "https://api.anthropic.com/v1/organizations"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_ADMIN_API_KEY")
        if not self.api_key.startswith("sk-ant-admin"):
            raise ValueError("需要 Admin Key（sk-ant-admin... 开头）")
        self.headers = {
            "anthropic-version": "2023-06-01",
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def get(self, endpoint: str, **params):
        r = requests.get(f"{self.BASE}/{endpoint}",
                         headers=self.headers, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

# 最近 7 天按模型聚合
client = AnthropicAdminAPI()
end = datetime.combine(datetime.utcnow(), time.min)
resp = client.get(
    "usage_report/messages",
    starting_at=(end - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    ending_at=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    bucket_width="1d",
    **{"group_by[]": ["model"]},
)
for bucket in resp["data"]:
    for r in bucket["results"]:
        print(r["model"], r["uncached_input_tokens"], r["output_tokens"])
```

**工程提示**：

- **Admin Key 和普通 Key 是两套权限**。`sk-ant-admin...` 在 Console → Settings → Admin Keys 里单独生成，**不能调 `messages.create`**——它只用于读 admin 端点。生产里把它放在单独 secret、单独权限里。
- **bucket_width 有硬限制**：usage 端点支持 `1m` / `1h` / `1d`；cost 端点**只支持 `1d`**，最多 31 天/请求。要拿月度数据必须分页 + 跨多个请求拼。
- **Priority Tier 成本永远拿不到**。Cookbook 明确说："Priority Tier uses a different billing model and will never appear in the cost endpoint"——usage 端点能看 token 数，但 cost 端点查不到 USD。要做 P0 监控就别用 Priority Tier。
- **分页靠 `has_more` + `next_page`**，**没有 cursor token**。Cookbook 的 `fetch_all_usage_data()` 循环 while `has_more`，最多 `max_pages` 兜底——生产里加 `max_pages=100`，防止 API 异常时死循环。

---

## 2. Tool Evaluation XML 框架：单任务评测

**一行定位**：用一份 XML 评测文件（`<task><prompt>` + `<response>`）+ 一组 tool schema，跑一遍 agent loop，用 XML 标签抽取 + 字符串相等判分，输出 markdown 报告。

**最小代码**（评测文件格式）：

```xml
<evaluation>
    <task>
        <prompt>Calculate the compound interest on $10,000 at 5% APR,
                compounded monthly for 3 years. Round to 2 decimal places.</prompt>
        <response>11614.72</response>
    </task>
    <task>
        <prompt>Calculate the pH of a 3.5 × 10^-5 M H+ solution.
                Round to 2 decimal places.</prompt>
        <response>4.46</response>
    </task>
</evaluation>
```

**Agent + 评测函数**：

```python
import re, time
from anthropic import Anthropic

EVALUATION_PROMPT = """You are an AI assistant with access to tools.
- Provide summary of each step, wrapped in <summary> tags
- Provide feedback on the tools provided, wrapped in <feedback> tags
- Provide your final response, wrapped in <response> tags
For numeric responses, provide just the number. If you cannot solve the task,
return <response>NOT_FOUND</response>. Your response should go last."""

client = Anthropic()
model = "claude-sonnet-4-6"

def agent_loop(prompt, tools):
    """简化版 tool-use loop，记录每个 tool 的调用次数和耗时"""
    messages = [{"role": "user", "content": prompt}]
    metrics = {}  # {tool_name: {"count": N, "durations": [...]}}
    while True:
        resp = client.messages.create(
            model=model, max_tokens=4096,
            system=EVALUATION_PROMPT, messages=messages, tools=tools,
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            break
        tool_use = next(b for b in resp.content if b.type == "tool_use")
        t0 = time.time()
        tool_result = dispatch(tool_use.name, tool_use.input)   # 业务侧分发
        metrics.setdefault(tool_use.name, {"count": 0, "durations": []})
        metrics[tool_use.name]["count"] += 1
        metrics[tool_use.name]["durations"].append(time.time() - t0)
        messages.append({"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": tool_use.id, "content": tool_result,
        }]})
    return next((b.text for b in resp.content if hasattr(b, "text")), None), metrics

def evaluate(task, tools):
    text, metrics = agent_loop(task["prompt"], tools)
    response = re.findall(r"<response>(.*?)</response>", text, re.DOTALL)
    actual = response[-1].strip() if response else None
    return {
        "prompt": task["prompt"], "expected": task["response"],
        "actual": actual, "score": int(actual == task["response"]),
        "tool_calls": metrics,
    }
```

**工程提示**：

- **XML 评测文件的硬约束**：`<prompt>` 是用户输入、`<response>` 是 gold answer——**只支持字符串完全相等判分**。所以这模式只适合"答案明确"的场景（数值、ID、单词）。模糊匹配的场景用 §5 的 model-as-judge。
- **判分函数要分桶**。Cookbook 的 calculator 例子所有题都判 `int(response == expected)`，对数值题就过——但**空格 / 大小写 / 千分位**会让 100% 的正确答案被判 0 分。生产里至少加 `re.sub(r"\s+", "", actual) == re.sub(r"\s+", "", expected)` 这种预处理。
- **tool description 写得好不好，直接影响评测分数**。Cookbook 故意把 calculator tool 的 `description` 和参数 `description` 都设为 `""`——这是为了演示**坏 description 会让模型乱调工具**。生产里写完 tool 第一件事：跑 5-8 个 task 看看 `<feedback>` 标签里模型说什么，按反馈改 description。

---

## 3. Agentic Search Harness：跑长链路基准

**一行定位**：用 `web_search` + `web_fetch` + `code_execution` 的"程序化调用"组合，配 `thinking: adaptive` + `effort: max` + `task_budget`，复现 Anthropic 在 DeepSearchQA / BrowseComp 上的官方分数。

**最小代码**（核心配置）：

```python
import anthropic

MODEL = "claude-sonnet-5"
GRADER_MODEL = "claude-opus-4-6"     # ← 关键：评测模型固定用更强的 Opus

# 长链路必须延长超时：单次 stream() 内部可能跑 30+ tool calls 几分钟
client = anthropic.Anthropic(
    max_retries=20,
    timeout=anthropic.Timeout(5.0, read=3600.0, write=600.0, pool=600.0),
)

TOOLS = [
    {"type": "code_execution_20260521", "name": "code_execution"},
    {"type": "web_search_20260318", "name": "web_search",
     "max_uses": 10_000,
     "allowed_callers": ["code_execution_20260521"],     # ← 关键：只允许沙箱内调
     "response_inclusion": "excluded"},                   # ← 关键：结果不进 context
    {"type": "web_fetch_20260318", "name": "web_fetch",
     "max_uses": 10_000, "max_content_tokens": 1_000_000,
     "allowed_callers": ["code_execution_20260521"],
     "response_inclusion": "excluded"},
]
BETAS = ["compact-2026-01-12", "task-budgets-2026-03-13"]

THINKING = {"type": "adaptive"}     # 让模型自己决定什么时候该想
OUTPUT_CONFIG = {
    "effort": "max",                                  # 用模型卡报告的最高档
    "task_budget": {"type": "tokens", "total": 3_000_000},   # 跨 turn 的输出预算
}

# 触发压缩 + 自定义摘要指令（最容易被忽视的杠杆）
COMPACT_INSTRUCTIONS = (
    "Your summary MUST begin by restating the user's ORIGINAL QUESTION "
    "verbatim in <original_question>...</original_question> tags. "
    "Then summarize key sources found, partial answers, and what remains. "
    "Your summary MUST also include this verbatim: "
    "'Provide your final answer wrapped in <result>...</result> tags.'"
)
CONTEXT_MANAGEMENT = {"edits": [{
    "type": "compact_20260112",
    "trigger": {"type": "input_tokens", "value": 200_000},
    "instructions": COMPACT_INSTRUCTIONS,
}]}
```

**工程提示**：

- **`allowed_callers` + `response_inclusion: "excluded"` 是评测分数的第一杠杆**。一个 deep research 题能触发 50+ 次 `web_fetch`，不这样配置的话每次结果都进 context，**直接超 context window**。Cookbook 的原话："for deep research this is essential"。
- **`COMPACT_INSTRUCTIONS` 比 trigger 阈值更重要**。Cookbook 明确说："Without them, the post-compaction agent has a summary of *what it found* but not *what it was asked*... scores zero"。**指令里必须包含"原题复述"和"答案格式"**两件事。
- **timeout 是分档的**。`Timeout(5.0, read=3600.0, write=600.0, pool=600.0)`——`read=3600` 是关键：单个 stream 事件最长等 1 小时。**默认 60s 直接挂**。
- **`max_retries=20`**：单次跑几百题时中途遇到 429/529 是常态。SDK 默认 2 次重试不够——一次完整 benchmark 跑 2 小时，中途 5 分钟断网就全废。

---

## 4. Programmatic Tool Calling：评测的最大杠杆

**一行定位**：把 `web_search` / `web_fetch` 从"Claude 直接调的工具"降级成"沙箱里 Python 代码调的库"——结果不进 context、只在沙箱里读、最后只 surface 摘要，**50+ 次 fetch 也不会爆 context**。

**最小代码**：

```python
# Claude 在沙箱里写的 Python（自动生成的代码长这样）：
import anthropic_client as ac

results = []
for q in ["Q1 2024 bank CEO tenure", "JPMorgan CEO since", "Jamie Dimon appointment"]:
    results.append(ac.web_search(query=q, max_results=5))

# Claude 在沙箱里读每个结果，**这些结果不进 main context**：
for r in results:
    print(r.title, r.snippet)

# 最后只把打印的输出 surface 回 main conversation
```

**对比数据**：

| 方式 | 单次 deep research context 占用 | 能跑几题 |
|---|---|---|
| 不用 PTC（web_search 直接调） | 50+ fetch × ~5K token = 250K+ | 1 题就要压缩或超限 |
| 用 PTC（沙箱内调） | 只 surface 摘要 ~2K token | 1 题轻松 200K context |

**工程提示**：

- **PTC 的核心是"转换协议边界"**——把"LLM ↔ 工具"变成"LLM → 代码 → 工具 → 代码 → LLM"。**好处**：工具结果不进 LLM context，省 token、省 attention 噪音；**代价**：debug 比直接调难，错误处理要写到 sandbox 代码里。
- **不是所有工具都适合 PTC**。PTC 要求工具是"沙箱内 Python 代码能调的 API"——HTTP / DB / 文件都好做，但像 `messages.create` 这种"要 LLM 决策的"就不适合（套娃递归）。Cookbook 默认只把 `web_search` / `web_fetch` 标 `allowed_callers: ["code_execution"]`。
- **`response_inclusion: "excluded"` 是必配**。就算配了 `allowed_callers`，**默认 tool result 还是会进 context**——`excluded` 才是关键开关。Cookbook 把它和 `allowed_callers` 配对出现。

---

## 5. Model-as-Judge Grader：F1 + 抽取 `<result>`

**一行定位**：用更强的模型（`claude-opus-4-6`）当裁判，喂"问题 + 标准答案 + 响应"让它输出 XML 评分——再解析 XML 算 precision / recall / F1。

**最小代码**：

```python
# 1) prompt 模型把答案包在 <result> 标签里（评测时才能精确抽取）
USER_PROMPT = """I want you to answer the following question.
<question>{question}</question>
First plan out your response. Then provide a short and concise answer
in <result> tags. For multiple answers, separate them with commas."""

# 2) 评测 prompt：让 grader 模型按固定 XML 输出
GRADER_PROMPT = """Your task is to evaluate whether a given response arrived at the correct answer.
Question: <question>{question}</question>
Correct answer (type: {answer_type}): <correct_answer>{answer}</correct_answer>
Response to evaluate: <response>{response}</response>

For each expected answer item, indicate whether it appears in the response.
Then list any answers in the response that are NOT in the correct-answer list.
Wording does not need to match exactly.

Reply in this exact XML format:
<evaluation>
  <explanation>one sentence</explanation>
  <correctness_details>
    <item answer="expected_item_1" correct="true|false"/>
  </correctness_details>
  <excessive_answers>
    <item>extra_item_if_any</item>
  </excessive_answers>
</evaluation>"""

# 3) 解析 + 算 F1
import re

def grade(client, grader_model, question, response_text):
    extracted = extract_result_tag(response_text) or response_text
    msg = client.messages.create(
        model=grader_model, max_tokens=1024,
        messages=[{"role": "user", "content": GRADER_PROMPT.format(
            question=question["problem"], answer=question["answer"],
            answer_type=question["answer_type"], response=extracted)}],
    )
    grader_text = msg.content[0].text
    items = re.findall(r'<item\s+answer="([^"]+)"\s+correct="(true|false)"\s*/?>',
                       grader_text)
    ex_block = re.search(r"<excessive_answers>(.*?)</excessive_answers>",
                         grader_text, re.DOTALL)
    excessive = re.findall(r"<item>([^<]+)</item>", ex_block.group(1)) if ex_block else []

    n_correct = sum(1 for _, c in items if c == "true")
    submitted = n_correct + len(excessive)
    precision = n_correct / submitted if submitted else 0.0
    recall    = n_correct / len(items) if items else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {"precision": precision, "recall": recall, "f1": f1,
            "extracted": extracted}

# 4) BrowseComp 单答案场景：用 A/B/C 单字母评分（更便宜、更快）
BROWSECOMP_GRADER = """...
Consider these statements about the sample answer:
 (A) It matches the ground-truth answer.
 (B) It does not match the ground-truth answer.
 (C) It says something like "I'm not sure" or "I don't know".
Respond with exactly one letter (A, B, or C) and nothing else."""
```

**工程提示**：

- **Grader 模型要"和被测模型错开"**。Cookbook 强制 `GRADER_MODEL = claude-opus-4-6`，**不管被测模型是 Sonnet 还是 Haiku**。用模型自己评自己 = 评分虚高 30%+，**跨模型不可比**。
- **只评 `<result>` 标签里的内容，不评整段 response**。Cookbook 的原话："feeding the whole response to the grader inflates both false positives and false negatives"。**先 `extract_result_tag()` 抽取再评分**是必备步骤。
- **F1 > 准确率**。set-valued 任务（"列出 3 个国家"）准确率会惩罚"多答对的"和"少答的"——F1 用 precision/recall 调和更准确。**BrowseComp 这种单答案任务用 accuracy**（`grader_letter == "A"`），因为 set-valued vs single-answer 是两种问题。
- **max_tokens 给 8（BrowseComp）或 1024（F1）**。BrowseComp 只要一个字母，**8 token 就够**——配合 streaming 时几乎免费；F1 grader 要写 XML 解释，**给 1024 不然会截断**。

---

## 6. 第三方生态地图：选 LlamaIndex / Pinecone / MongoDB / Voyage

**一行定位**：`third_party/` 收录了 7+ 主流框架的"Claude 集成样板"——按"RAG / 数据源 / 多模态 / 搜索"分桶。

**生态地图**：

| 子目录 | 框架 | 解决的问题 | 集成形态 |
|---|---|---|---|
| `Pinecone/` | Pinecone 向量库 | RAG 检索 + agentic RAG | `claude_3_rag_agent` / `rag_using_pinecone` |
| `LlamaIndex/` | LlamaIndex 编排 | RAG / Multi-Document Agent / ReAct / Router | 5 个 notebook：Basic_RAG / ReAct / Router / SubQuestion / Multi_Document / Multi_Modal |
| `MongoDB/` | MongoDB Atlas | 向量检索 + metadata 过滤 | Atlas Vector Search 集成 |
| `VoyageAI/` | Voyage Embeddings | 替换 OpenAI/Cohere embedder | voyage-2 / voyage-large-2 |
| `Wikipedia/` | Wikipedia API | 知识库检索 | 直接 HTTP + wikipedia 库 |
| `WolframAlpha/` | WolframAlpha | 数学 / 科学计算 | wolframalpha 库 + tool schema |
| `Deepgram/` | Deepgram ASR | 语音转文本 | audio 文件上传 + transcription tool |
| `ElevenLabs/` | ElevenLabs TTS | 文本转语音 | streaming TTS tool |

**工程提示**：

- **`third_party/` 不是"Anthropic 推荐"**——它是"第三方维护的样板"。Cookbook 明确说这些 notebook 由第三方贡献者维护，**Anthropic 不保证 API 兼容性**。生产里用要先跑一遍、确认 SDK 版本还在维护。
- **选型路径**：
  - **简单 RAG** → `Pinecone/rag_using_pinecone` 或 `LlamaIndex/Basic_RAG_With_LlamaIndex`（pick one，不要两个都学）
  - **多文档 / 复杂查询** → `LlamaIndex/Multi_Document_Agents`（一个文档一个 agent，比 single-agent 大文档好得多）
  - **语音场景** → `Deepgram`（ASR）+ `ElevenLabs`（TTS）+ Claude（理解）三件套
  - **数学 / 物理 / 化学** → `WolframAlpha` 比让 Claude 自己算强 100 倍
- **集成样板的核心价值是 schema 适配**。每个 notebook 里最有用的部分是"怎么把第三方 SDK 的输入输出映射到 Claude 的 tool schema"——**schema 写得对，模型就能调对**；schema 写得错，模型调飞。

---

## 落地清单

| 场景 | 优先模式 | 解决的问题 |
|---|---|---|
| 生产 token / cost 监控 | #1 Usage & Cost API | 财务分摊 / 异常告警 |
| 评测一个 tool definition | #2 Tool Evaluation XML | tool description 优化 |
| 跑长链路 agent 基准 | #3 Agentic Search Harness | 复现官方分数 / 自建 benchmark |
| 评估"工具描述好不好" | #2 + #5 F1 grader | A/B tool description |
| 选型第三方框架 | #6 third_party map | 决定用 Pinecone 还是 LlamaIndex |
| 评测 set-valued 输出 | #5 Model-as-Judge F1 | 多答案题打分 |

## 选型速查

```
你的目标是：
├─ 监控生产数据 → Usage & Cost Admin API（#1）
├─ 评测一个 tool 的可用性 → Tool Evaluation XML（#2）
├─ 跑 deep research 基准 → Agentic Search Harness（#3）
│   ├─ 调 50+ 次 web_fetch 会爆 context → PTC（#4）
│   ├─ 评分靠 F1 → Model-as-Judge（#5）
│   └─ 单答案（BrowseComp）→ A/B/C 单字母 grader（#5 变体）
└─ 选第三方框架 → third_party 生态地图（#6）
```

**反向警告**：以下场景**不要用** 这 6 个模式：

- **实时监控**：Usage & Cost API 是 T+1（按天聚合），不是实时——实时监控用 LangSmith / Helicone / 自建 OTLP pipeline。
- **评测主观质量**（写作风格 / 创意）：Model-as-Judge 的 F1 是机械打分，**主观题用 pairwise preference + human eval**（参考 LMSys Chatbot Arena 方法论）。
- **小规模调试**：单个 case 看就够，**别动不动就跑全套评测**——一次完整 DeepSearchQA 跑 2 小时、几百美元。

## 与其它模式的关系

- **评测 vs 成本优化**：[成本优化 7 模式](blog/posts/2026-09-15-cost-optimization-engineering.md) 里的 `usage_cost()` 是"单请求成本估算"，**这里 #1 是"组织级成本聚合"**——一个看单条、一个看板。
- **评测 vs Skills**：[Skills 6 模式](blog/posts/2026-09-15-claude-skills-engineering.md) 里的自定义 skill 可以挂评测脚本——**评测逻辑可以打包成 skill**，让 Claude 在生成时主动评估自己。
- **PTC vs Tool Use**：[Tool Use 7 模式](blog/posts/2026-09-15-tool-use-engineering-patterns.md) 里的 `programmatic_tool_calling_20250924` 是 PTC 的最小用法，**#4 是 PTC 在评测场景的极致形态**——50+ 工具调用 + 排除 context + streaming。
- **第三方 vs RAG**：[RAG 5 模式](blog/posts/2026-09-15-rag-engineering-patterns.md) 是"RAG 怎么设计"，**`third_party/Pinecone/` 和 `third_party/LlamaIndex/` 是"RAG 怎么落地"**——把 RAG 模式和框架样板结合就是完整方案。
- **评测 vs Agent**：评测 harness 是"长链路 agent 的标准化环境"——参考 [Patterns/Agents 6 模式](blog/posts/2026-09-15-patterns-agents-engineering.md) 里的 orchestrator-workers，可以做 multi-agent 对比评测。

参考资料：

- [observability/usage_cost_api.ipynb](https://github.com/anthropics/claude-cookbooks/tree/main/observability)
- [tool_evaluation/tool_evaluation.ipynb](https://github.com/anthropics/claude-cookbooks/tree/main/tool_evaluation)
- [evals/agentic_search/reproduce_agentic_search_benchmarks.ipynb](https://github.com/anthropics/claude-cookbooks/tree/main/evals/agentic_search)
- [third_party/](https://github.com/anthropics/claude-cookbooks/tree/main/third_party)
- [Usage & Cost Admin API 官方文档](https://docs.claude.com/en/api/admin-api)
- 配套阅读：[成本优化 7 模式](blog/posts/2026-09-15-cost-optimization-engineering.md)、[Skills 6 模式](blog/posts/2026-09-15-claude-skills-engineering.md)