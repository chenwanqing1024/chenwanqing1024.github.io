---
title: Building Effective Agents 拆解：Workflows vs Agents 的 6 个工程取舍
date: 2026-09-15
tags: [Claude, AI 工程, Agent, Workflow]
summary: 把 Anthropic Building Effective Agents 拆成 6 个工程取舍：workflows vs agents 的边界（确定路径 vs 自主决策）、5 个 workflow 模式（prompt chaining / routing / parallelization / orchestrator-workers / evaluator-optimizer）、3 个核心原则（simplicity / transparency / well-crafted ACI）、customer support + coding agent 两个工程落地参考、prompt engineering your tools 的元教训。配代码示例 + 面试可讲的设计决策。
source-url: https://www.anthropic.com/engineering/building-effective-agents
source-title: Building effective agents
source-author: Erik Schluntz, Barry Zhang (Anthropic)
---

## 引子

Anthropic 这篇是 Agent 工程领域的"开山文"——**它把 LLM 应用分成 workflows（确定性路径）和 agents（自主决策）两类**——并明确警告：**"Don't build agents for everything"**。这是 2024 年 12 月的奠基性文章，**整个 Agent 工程领域（tool use、context engineering、managed agents、sandboxing）都以这篇文章的术语体系为起点**。理解 workflows vs agents 的边界，比学任何具体模式更重要——**因为选错范式 = 复杂系统解决简单问题**。

下面拆 6 个工程取舍，按"**范式边界 → 5 个 workflow 模式 → 自主 agents → 3 个核心原则 → 工程参考 → 元教训**"递进。

---

## 1. 范式边界：Workflows vs Agents 不是二选一，是光谱

**一行定位**：**Workflows = LLM + 固定代码路径**，**Agents = LLM 自己决定路径**——**两者是 spectrum，不是 binary**。

| 维度 | Workflows | Agents |
|---|---|---|
| 路径决定者 | 程序员（事先写好） | LLM（运行时决定） |
| 适用场景 | 任务明确、可拆解 | 任务开放、步骤数未知 |
| 失败模式 | 固定流程不匹配 | 模型决策错 / loop |
| 成本 | 低（每步可预测） | 高（token 不可控） |
| Debug | 易（trace 每步） | 难（要看 transcript） |
| 信任假设 | LLM 不会乱走 | LLM 会按 prompt 决策 |

**Anthropic 的强警告**：

> "When building applications with LLMs, we recommend finding the simplest solution possible... Don't build agents for everything."

**核心论点**：**够用就好**。**能用 prompt 解决的不要用 workflow，能用 workflow 解决的不要用 agent**。**复杂度是成本，不是 feature**。

**怎么选**：
- **任务完全定义明确** → 单次 prompt 或 chain
- **任务有清晰子步骤** → workflow（5 个模式）
- **任务步骤数 / 路径动态变化** → agent

**面试可讲的角度**：这是 *engineering complexity budget*——**软件工程的铁律是"用最简单的方案解决"**。**AI 时代有些团队把所有东西都包装成 agent 是 over-engineering**。**能单 LLM call 解决就别上 agent**。

**工程落地**：
- ☐ **先用单 prompt 试**——能 work 就别上 workflow
- ☐ **Workflow 还是 Agent 看"路径是否动态"**——固定流程用 workflow，开放探索用 agent
- ☐ **每加一层抽象都有 cost**——orchestrator / routing / eval layer 都是 cognitive load + token cost
- ☐ **能 offline 测的不要 online 决策**——把动态决策 offline 化，**runtime 只跑简单逻辑**

---

## 2. 五个 Workflow 模式：拼装出 80% 的生产 LLM 应用

**一行定位**：**Anthropic 官方给的 5 个 workflow 模式 cover 了大部分生产 LLM 应用**——**不是越新越好，是越匹配越好**。

### 模式 1: Prompt Chaining（提示链）

**机制**：把任务拆成 fixed sequence 的 LLM calls，**前一个的 output 是后一个的 input**。**中间可以插 deterministic code（检查、转换）**。

```
Input → LLM Call 1 → Check → LLM Call 2 → Check → Output
```

**典型场景**：
- **翻译 + 校对**：先翻译 → 写检查 script 找问题 → 再翻译修正。
- **Marketing copy 生成**：先生成 → 写检查（字数 / 关键词）→ 不通过就重写。
- **SQL 生成**：生成 → 执行 → 报错就 re-prompt 修正（见 sql-agent-pattern）。

**Code 示例**：
```python
def generate_marketing_copy(topic: str) -> str:
    # Step 1: 生成初稿
    draft = llm_call(f"Write a marketing paragraph about {topic}")
    
    # Step 2: deterministic check
    if not has_required_keywords(draft) or len(draft) > 500:
        # Step 3: 重新生成 with 反馈
        draft = llm_call(f"Rewrite with constraints: {get_issues(draft)}")
    
    return draft
```

**面试可讲的角度**：这是 *pipeline pattern*——**LLM 当 stage，code 当 stage 之间 glue**。**类比 Unix pipeline**：`cat | grep | awk | sort`——每个 stage 一个职责，stage 之间用 deterministic 转换。

### 模式 2: Routing（路由）

**机制**：**对 input 做分类 → 不同类型走不同 path**。**LLM 当 classifier 或 router**。

**典型场景**：
- **客服问题分类**（refund / general / technical）→ 不同 prompt / 不同 model。
- **Code 任务分模型**（简单用 Haiku，复杂用 Sonnet）。
- **Multi-language**：英文 → 不同 prompt，中文 → 不同 prompt。

**Code 示例**：
```python
def route_query(query: str) -> str:
    category = llm_classify(query, categories=["refund", "general", "technical"])
    if category == "refund":
        return refund_agent.run(query)
    elif category == "technical":
        return technical_agent.run(query)
    else:
        return general_agent.run(query)
```

**面试可讲的角度**：这是 *strategy pattern*——**多算法一族，每种 case 选最合适的**。**类比 web framework 的 URL routing**：根据 path 选 handler。

### 模式 3: Parallelization（并行化）

**机制**：**LLM 同时跑多个独立任务，结果聚合**。两种 sub-mode：

**Sectioning（切片）**：
- 把 input 拆成独立 chunks → 多个 LLM 并行处理 → 结果合并。
- 例子：把 100 个文档摘要拆给 5 个 LLM 同时跑。
- 节省 5x 时间。

**Voting（投票）**：
- **同一 prompt 跑多次** → 不同 output → 用 majority / best-of 选。
- 例子：code generation 跑 5 次 → 用 unit test 验 → 选 pass 的。
- **提升 reliability + 验 boundary case**。

**Code 示例（Sectioning）**：
```python
import asyncio

async def summarize_documents(docs: list[str]) -> list[str]:
    # 5 个 chunk 并行摘要
    chunks = [docs[i::5] for i in range(5)]
    summaries = await asyncio.gather(*[llm_summarize(chunk) for chunk in chunks])
    return merge_summaries(summaries)
```

**Code 示例（Voting）**：
```python
def generate_code_with_voting(prompt: str, n: int = 5) -> str:
    candidates = [llm_generate_code(prompt) for _ in range(n)]
    for candidate in candidates:
        if run_tests(candidate).all_pass:
            return candidate
    return candidates[0]  # fallback
```

**面试可讲的角度**：这是 *embarrassingly parallel*——**LLM call 之间没依赖时，并发是 free lunch**。**Voting 是 AI 时代的"consensus"**——类比 ensemble learning。

### 模式 4: Orchestrator-Workers（编排者-执行者）

**机制**：**中央 LLM（orchestrator）动态拆任务 → 派给 worker LLMs → 聚合**。**区别于 Parallelization：orchestrator 在 runtime 决定怎么拆**。

**典型场景**：
- **Multi-file code 修改**：orchestrator 看 codebase → 决定改哪些文件 → 派 worker 改。
- **Research task**：orchestrator 看 question → 决定需要哪些 sub-question → 派 worker 找 → 综合答案。

**Code 示例**：
```python
def orchestrator_research(question: str) -> str:
    # Orchestrator LLM 决定 sub-questions
    sub_questions = llm_call(f"What sub-questions need answering? {question}")
    
    # Workers 并行答
    answers = parallel_llm_calls(sub_questions)
    
    # Orchestrator 综合
    return llm_call(f"Synthesize: {question} | Answers: {answers}")
```

**面试可讲的角度**：这是 *task decomposition pattern*——**类比 MapReduce**：master 拆 map task，worker 跑 map，master 跑 reduce。**LLM 当 master + worker 都是 LLM**。

**关键区别 vs Parallelization**：Parallelization 的拆分是 **deterministic 程序员写好的**，orchestrator-workers 的拆分是 **LLM 动态决定的**。**Orchestrator-workers 更灵活但更难 debug**。

### 模式 5: Evaluator-Optimizer（评估者-优化者）

**机制**：**LLM A 生成 output → LLM B 评估 → 不达标反馈给 A 重新生成**。**形成 closed loop**。

**典型场景**：
- **Code generation + lint/eval pass**。
- **Translation 翻译 + 评估翻译质量**。
- **Search result 优化**（query rewrite + relevance eval）。

**Code 示例**：
```python
def generate_with_eval(prompt: str, max_iter: int = 3) -> str:
    output = llm_generate(prompt)
    for _ in range(max_iter):
        feedback = llm_evaluate(output, criteria=criteria)
        if feedback.passed:
            return output
        output = llm_generate(prompt, feedback=feedback)  # 带反馈重生成
    return output
```

**面试可讲的角度**：这是 *GAN-inspired loop*——**Generator + Discriminator 的 closed loop**。**关键约束**：**evaluator 必须 reliable**，**否则循环跑飞**（见 harness-design-gan-evaluator 的 evaluator tuning）。

### 5 个模式的关系

```
                    ┌─ Prompt Chaining (固定 sequence)
                    ├─ Routing (按 type 分流)
Workflows           ├─ Parallelization (并行 + 聚合)
                    ├─ Orchestrator-Workers (动态拆)
                    └─ Evaluator-Optimizer (生成 + 评估闭环)

Autonomous Agents   ─ LLM 自主决定：用哪些 tools、调几次、什么时候停
```

**工程落地**：
- ☐ **从 prompt chaining 开始**——最简单的能 work 就别升级
- ☐ **Routing 第一个要加**——multi-task 时按 type 分流省 token
- ☐ **Parallelization 是 free lunch**——独立 LLM call 必上 async
- ☐ **Orchestrator-workers 比 Parallelization 灵活但贵**——只用在"拆法真的动态"时
- ☐ **Evaluator-optimizer 别滥用**——evaluator 不可靠 = 越迭代越差

---

## 3. Autonomous Agents：让 LLM 自己选 tools

**一行定位**：**Agent = LLM 在 runtime 决定"调哪些 tool、调几次、什么时候停"**——**没有固定 path，LLM 自己规划**。

**典型场景**：
- **Coding agent**：Claude Code 风格，LLM 看 task → 决定用 Read / Edit / Bash / Grep → 循环到 done。
- **Customer support agent**：LLM 看 query → 决定查订单 / 退钱 / 升级 → 调到 done。
- **Research agent**：LLM 看 question → 决定 search 几次、读哪几个 page → 综合答案。

**Anthropic 的关键设计选择**：

> "Agents are appropriate when... the task cannot be easily decomposed into fixed sub-tasks, and requires dynamic problem-solving."

**核心论点是"动态问题解决"**——**如果是已知可拆的，用 workflow；如果是真正 open-ended 的，用 agent**。

**面试可讲的角度**：这是 *control flow inversion*——**传统程序 control flow 在程序员手里，agent 的 control flow 在 LLM 手里**。**这是根本范式转换**。

**风险**：
- **Token 不可控**——agent 可能跑 50 个 tool call。
- **失败难 debug**——要看 transcript 而不是 stack trace。
- **Trust 假设**——必须假设 LLM 决策是对的（**所以 sandboxing 必须**——见 claude-code-sandboxing-isolation）。

**工程落地**：
- ☐ **Agent 必上 sandbox**——filesystem + network 双隔离（claude-code-sandboxing）
- ☐ **设 max iter / max token**——**防 runaway**
- ☐ **Eval suite 必上**——**agent 的失败模式比 workflow 多一个数量级**（demystifying-ai-agent-evals）
- ☐ **Human-in-the-loop 关键决策**——refund / production deploy / 写数据库 不能 agent 自主

---

## 4. 三个核心原则：Simplicity / Transparency / Well-crafted ACI

**Anthropic 的三原则**——比模式本身更重要。

### 原则 1: Simplicity（简单）

> "Find the simplest solution possible. Only increase complexity when needed."

**工程落地**：
- ☐ **能 prompt 解决别上 workflow**
- ☐ **能 workflow 解决别上 agent**
- ☐ **每加一层抽象都要 question：真的需要吗？**

### 原则 2: Transparency（透明）

> "Explicitly lay out the steps the agent is taking makes it easier to understand where failures occur."

**具体动作**：
- **Workflow 步骤显式 log**——每步 input / output / decision 记录。
- **Agent decision log**——每个 tool call + reasoning 记录。
- **可视化 trace**——**让 developer 能看 transcript**。

**为什么重要**：**LLM 失败不是 exception 是常态**——必须能回放、必须能 debug。

**面试可讲的角度**：这是 *observability*——**没有 log = 不可维护**。**LLM 系统的 observability 比传统系统更关键**（因为失败模式更不可预测）。

### 原则 3: Well-crafted ACI（Tool Interface 精心设计）

> "Give the model well-crafted tools... the same principles as good human UI design."

**核心论点**：**Tool 是 LLM 的 UI**——**tool 的 design 决定 agent 的 productivity**。**这是整篇 writing-tools-for-agents 的预告**。

**工程落地 checklist**：
- ☐ **Tool description 写得像 onboarding**——给新员工的 context
- ☐ **Tool 命名 unambiguous**——`user_id` 不是 `id`
- ☐ **Tool 边界清晰**——`create_xxx` 不混入 `update_xxx`
- ☐ **Few-shot examples 进 tool def**（见 advanced-tool-use-three-features）

---

## 5. 工程落地参考：Customer Support + Coding Agent

**Anthropic 给的两个典型 use case**。

### Use Case 1: Customer Support Agent

**架构**：
```
Customer Query
   ↓
   [Conversation Agent] → 收集 context + 走 workflow
   ↓
   [Refund Tool] / [Order Status Tool] / [FAQ Tool]
   ↓
   Response to Customer
```

**关键设计**：
- **对话 agent + 工具**——不是纯 LLM。
- **Tool 受限**——只能调几个 specific actions（refund、查订单）。
- **Sensitive 操作人类 review**——refund > $X 必须人工。

**面试可讲的角度**：这是 *agent + workflow hybrid*——**核心流程 agent 自主（对话），关键 action 走 tool 边界（受限）**。**类比 RBAC**——agent 有 role，每个 action 配 permission。

### Use Case 2: Coding Agent

**架构**：
```
User Request
   ↓
   [Coding Agent] → 决定下一步
   ↓
   [Read file] / [Edit file] / [Bash] / [Grep] / [Glob]
   ↓
   ... (循环到完成)
```

**关键设计**：
- **Agent 自主**——不知道需要调几次 tool。
- **Tools 受限**——Read / Edit / Bash / Grep，**不能 rm -rf / /etc/passwd**。
- **Sandbox 保护**——filesystem + network 双隔离（见 claude-code-sandboxing-isolation）。

**这就是 Claude Code**——**Anthropic 自己用同样的模式建了 coding agent**。

**面试可讲的角度**：**Customer support 和 coding agent 是 agent 的"两端"**——customer support **步骤少但每步 critical**（refund 不能错），coding agent **步骤多但每步可回滚**（git revert）。**设计 trade-off 不同**。

---

## 6. 元教训：Prompt Engineering 你的 Tools

**Anthropic 在附录的元论点是**——**Tool 的 prompt 比 agent 的 prompt 重要**：

> "Just as important as the prompts you give the agent is the prompts you give it about its tools."

**核心论点**：
- **Tool description 就是 agent 的 prompt**。
- **改 tool description = 改 prompt = 直接影响 accuracy**。
- **Sonnet 3.5 在 SWE-bench 的 SOTA 不是模型升级——是 tool description 优化**（见 writing-tools-for-agents 的核心数据）。

**工程落地**：
- ☐ **Tool description 当 prompt 精炼**——像 onboarding doc
- ☐ **Tool examples 当 few-shot**——accuracy 72% → 90%
- ☐ **Tool naming 当 namespace**——`asana_search` 而不是 `search`
- ☐ **Eval 测 tool description**——**微小改动带来巨大 accuracy 提升**

**面试可讲的角度**：这是 *investment allocation*——**改 tool description 的 ROI 比改 agent prompt 高**。**这是 prompt engineering 的"下沉"**——**从 agent prompt 下沉到 tool prompt**。**Tool prompt 是 LLM 最常读的部分**——每次 tool call 都读。

---

## 一句话总结

Building Effective Agents 的核心论点是**"范式选择 > 模式选择 > 工具选择"**——**workflows vs agents 是 spectrum，先选最简的能 work 的**；**5 个 workflow 模式 cover 80% 生产场景，能用 workflow 解决就别上 agent**；**agent 适合真正 open-ended 任务但要 sandbox + eval + max iter 兜底**；**3 个核心原则是 simplicity / transparency / well-crafted ACI**；**改 tool description 比改 agent prompt 更有效**。**复杂是 cost，不是 feature——这是整个 AI 工程领域的元教训**。

## 配套阅读

- **架构视角**：managed-agents-arch-patterns — Pet vs Cattle + brain-hand decoupling
- **执行机制**：tool-use-engineering-patterns — Tool choice / parallel / structured output
- **范式选择**：harness-design-gan-evaluator — 哪种任务用 generator-evaluator loop

参考资料：

- [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) — Erik Schluntz, Barry Zhang, Anthropic
- [Building effective agents (Anthropic 重新发布版)](https://www.anthropic.com/engineering/building-effective-agents) — 2024 年 12 月奠基文
- [Anthropic Academy: Building agents](https://anthropic.skilljar.com/) — 配套课程
