---
title: AI Agent 评测实操：从 0 到 1 搭建评测体系的 8 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, Evals, Agent]
summary: 把 Anthropic Demystifying Evals 文章拆成 8 个可落地的工程模式：评测词汇表、三种 Grader 选择、Capability vs Regression 区分、4 类 Agent 的评测配方、pass@k vs pass^k、8 步 Roadmap、Grader 反模式、Swiss Cheese 多层监控。每个模式给定位 + 代码 / YAML 示例 + 落地 checklist。
source-url: https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
source-title: Demystifying evals for AI agents
source-author: Mikaela Grace, Jeremy Hadfield, Rodrigo Olivares, Jiri De Jonghe (Anthropic)
---

## 引子

AI Agent 评测是 AI 工程和传统软件工程最不一样的地方。传统软件上线后看 latency / error rate，**Agent 上线后还要看模型评测分数 + token 成本 + 工具调用成功率 + 行为漂移**。Anthropic 这篇 demystifying evals 是目前**最完整的 Agent 评测方法论**——它把 vocabulary 标准化、给 grader 选型决策树、按 Agent 类型给评测配方、给 0→1 落地路线。

下面拆成 8 个工程模式，按"**词汇 → Grader → 分类 → 落地 → 反模式**"递进。

---

## 1. 评测词汇表：先统一术语，再谈评测

**一行定位**：评测领域 7 个术语必须区分清楚——**task、trial、grader、transcript、outcome、harness、suite**。

**Anthropic 的定义**：
- **task**（problem / test case）：单个测试，有 input 和 success criteria。
- **trial**：一次 task 尝试。**Agent 输出有随机性，必须多 trial**才能稳定。
- **grader**：评分逻辑。**每个 task 可有多个 grader，每个 grader 含多个 assertion**。
- **transcript**（trace / trajectory）：**trial 的完整记录**——所有 tool call、reasoning、中间结果。Anthropic API 里就是 messages 数组。
- **outcome**：trial 结束时环境的**最终状态**。"你的航班已订"是 transcript，**reservation 真的在 DB 里是 outcome**。
- **evaluation harness**：跑 eval 的基础设施——分发指令、并发跑 task、记录步骤、评分、聚合。
- **agent harness**（scaffold）：让模型变成 agent 的系统——处理输入、编排 tool call、返回结果。**Eval "agent" 时，测的是 harness + model 一起工作**。

**面试可讲的角度**：transcript ≠ outcome 是最常被搞混的。**"Agent 说完事"和"事真的做完"是两件事**——必须分别测。

**工程落地**：
- **先在团队对齐术语**——7 个词定义清楚再谈评测。
- **transcript 永远存**——出问题时没 transcript 等于没调试能力。
- **outcome 测试独立于 transcript**——DB 状态 / 文件系统状态 / API 响应，**不要靠 Agent 自己说"我做了"**。

---

## 2. 三种 Grader：Code / Model / Human 的选型决策树

**一行定位**：**没有万能 grader**——**Code fast 但 brittle，Model flexible 但 non-deterministic，Human gold 但 expensive**。选型是 tradeoff。

**Anthropic 的对比**：

| 类型 | 方法 | 优势 | 劣势 |
|---|---|---|---|
| **Code-based** | 字符串匹配 / 单元测试 / 静态分析 / outcome 验证 / tool call 验证 / transcript 分析 | 快、便宜、客观、可复现、易调试、验证特定条件 | 对 valid variation 容易 brittle、缺 nuance、不适合主观任务 |
| **Model-based** | rubric 评分 / 自然语言断言 / pairwise 比较 / 参考答案评估 / 多 judge consensus | 灵活、可扩展、捕捉 nuance、处理开放式任务 | 非确定、比 code 贵、需 human 校准 |
| **Human** | SME review / 众包判断 / 抽查 / A/B 测试 / 评分一致性 | 金标准质量、匹配专家判断、用于校准 model grader | 贵、慢、规模化需专家 |

**面试可讲的角度**：**不存在"用 LLM judge 替代一切"的方案**——三者必须组合。LLM judge 必须定期 human 校准，否则漂移到没意义。

**工程落地**：
- **能 Code 就 Code**——只要 outcome 可验证（DB state、file content、test pass），不浪费 model judge 配额。
- **LLM judge 加 "Unknown" 选项**——给模型"我不知道"的退路，**比强制打分的 hallucination 风险低一个数量级**。
- **每个 grader 维度独立 judge**——不要一个 LLM judge 一次评所有维度，**会因 token 长度和顺序导致 bias**。
- **定期 human 校准**——LLM judge 跑 100 次，找 5-10 个 case 给 human 比对，**drift 超过阈值就重写 prompt**。

---

## 3. Capability vs Regression：两种目标不同，分两套

**一行定位**：**Capability eval 是"山"，Regression eval 是"网"**——一个爬升、一个兜底。

**Anthropic 的区分**：
- **Capability / quality eval**：问"agent 能做什么？"**起始 pass rate 要低**（10-30%），给团队一座山爬。
- **Regression eval**：问"agent 还能做原来能做的吗？"**pass rate 接近 100%**，保护不下掉。
- **生命周期**：capability eval 分数爬到 95%+ → "graduate" 成 regression suite 永久跑。

**面试可讲的角度**：这是 *innovation vs stability* 的工程表达。**只有 innovation 没有 stability = 上线崩；只有 stability 没有 innovation = 不进步**。

**工程落地**：
- **两套 eval 必须并行跑**——只跑 capability 是赌"我们改的东西没碰 regression"；只跑 regression 是没在进步。
- **regression eval 必须窄而硬**——每个 case pass/fail 明确，**不要把 capability 误判为 regression**。
- **capability eval 定期 graduated 审查**——100% pass 的 case 移到 regression，**空出能力测空间**给更难 task。

---

## 4. 四类 Agent 评测配方：不同类型不同解

**Anthropic 按 agent 类型给的配方**：

### Coding Agent（coding 评测）
- **核心方法**：unit tests + integration tests。SWE-bench Verified / Terminal-Bench 是标杆。
- **附加**：LLM rubric 评 code quality、static analysis（lint/type/security）、state_check（DB / filesystem）、tool_calls 必须出现 / 不能出现。
- **示例 YAML**（节选）：

```yaml
task:
  id: "fix-auth-bypass_1"
  graders:
    - type: deterministic_tests
      required: [test_empty_pw_rejected.py, test_null_pw_rejected.py]
    - type: llm_rubric
      rubric: prompts/code_quality.md
    - type: static_analysis
      commands: [ruff, mypy, bandit]
    - type: state_check
      expect:
        security_logs: {event_type: "auth_blocked"}
    - type: tool_calls
      required:
        - {tool: read_file, params: {path: "src/auth/*"}}
        - {tool: edit_file}
        - {tool: run_tests}
  tracked_metrics:
    - {type: transcript, metrics: [n_turns, n_toolcalls, n_total_tokens]}
    - {type: latency, metrics: [time_to_first_token, output_tokens_per_sec]}
```

### Conversational Agent（对话评测）
- **核心方法**：**verifiable end-state + 多维度 rubric**——task 完成 + turn 数 + 语气。
- **关键**：**用第二个 LLM 模拟用户**（τ-Bench / τ2-Bench）。
- **多维度示例**：refund 任务同时测 outcome（ticket resolved、refund processed）、transcript constraint（≤10 turn）、LLM rubric（empathy、清晰度、tool-grounded）。

### Research Agent（研究评测）
- **核心方法**：**groundedness + coverage + source quality**。BrowseComp 找开放网络里的"needle in haystack"。
- **特殊性**：研究质量主观，**ground truth 随参考内容变**。**LLM rubric 必须频繁 human 校准**。

### Computer Use Agent（电脑操作评测）
- **核心方法**：真实 / 沙箱环境跑 + outcome 验证。WebArena / OSWorld 是标杆。
- **特殊技巧**：DOM 操作快但 token 多；screenshot 操作慢但 token 省。**按场景选（提取文本用 DOM、找视觉元素用 screenshot）**。

**面试可讲的角度**：评测配方不是 universal——**agent 类型决定 grader 选型**。代码 agent 的 lint grader 对话 agent 用不上，反之亦然。

**工程落地**：
- **别发明评测**——用现有 benchmark（SWE-bench、τ-Bench、BrowseComp、OSWorld）做起点，再扩你的 domain 任务。
- **每个 eval 加 groundedness check**——研究 agent 答错事的最常见原因是 hallucination，**citation check 比答案 check 更早发现问题**。
- **Computer use 必须真环境**——DOM 解析再准，也测不出"按钮点不上"的真 bug。

---

## 5. pass@k vs pass^k：选哪个看你场景

**一行定位**：**pass@k = "至少 1 次成功"，pass^k = "次次成功"**——同样的 task，**k=10 时两者讲相反故事**。

**Anthropic 的对比**：
- **pass@1**：coding eval 关心——找到 solution 的首次成功率。
- **pass^k**：客服 agent 关心——用户每次都要可靠，不能靠"再来一次碰运气"。
- 75% per-trial success，3 trials：**pass@3 ≈ 98%，pass^3 ≈ 42%**。

**面试可讲的角度**：这是 *reliability vs exploration* 的 metric 表达。**所有"k 次中"指标都是赌概率**——选 k=多少决定了你赌的 game。

**工程落地**：
- **生产 agent 用 pass^k**（k≥3，**强制 multi-trial consistency**）。
- **一次性 agent（research / one-shot 生成）用 pass@k**（k=1 即可）。
- **报告 eval 时同时给**——只报一个会误导。

---

## 6. 8 步 Roadmap：从 0 到 1 搭评测体系

**Anthropic 的工程路线**：

### Step 0: 早开始
- **20-50 个真实 task 起步够了**——别等"完美 suite"。
- 早期 change effect size 大，小样本足够。

### Step 1: 从你已经在测的事开始
- **Bug tracker + 客服 ticket = 评测金矿**。**用户报 bug → 转 eval task**。

### Step 2: 写 unambiguous task + reference solution
- **两个 domain expert 独立判定能拿到同结果 → 才是好 task**。
- **每个 task 必须有 reference solution**——已知能 pass 的输出，**证明 task 可解 + grader 配对**。
- **0% pass rate 跨多 trial 通常是 task 坏了**，不是 agent 不行。

### Step 3: 平衡 problem set
- **必须测"应该做"和"不应该做"两个方向**——单方向测会让 agent 过度触发。
- 例：测 web search 时同时测"该搜"（天气）和"不该搜"（"苹果谁创办的"）。

### Step 4: 稳定环境的 eval harness
- **每个 trial 从 clean environment 开始**——残留文件 / 缓存 / 资源耗尽会让 trial 不独立。
- **共享状态会膨胀分数**——内部曾发现 Claude 看 git history 找到上 trial 的答案。

### Step 5: 仔细设计 grader
- **测 outcome，不测 path**——**别强制 tool call 顺序**，模型会找到你没想过的 valid approach。
- **多组件任务给 partial credit**——找到问题但没解决 > 啥都没做。
- **LLM judge 配 Unknown 选项**。

### Step 6: 读 transcript
- **失败要看 transcript 确认"agent 真错了"而不是"grader 误判"**。
- **Anthropic 投了钱做 transcript viewer**——这是必要工具。

### Step 7: 监控 saturation
- **eval 100% pass = 没信号了**。**SWE-bench Verified 已饱和 ~80%**。
- **饱和后继续投模型 = 进步看着小**——做长任务、复杂任务的 eval。

### Step 8: 长期维护 + open contribution
- **Eval suite 是活 artifact**——需要 ownership。
- **Eval-driven development**：**先写 eval 定义成功标准，再实现**。PM / CSM / 销售能写 eval task 就让他们写。

**面试可讲的角度**：这是 *eval as product specs*——**评测不是测试，是产品需求文档的 executable form**。

**工程落地 checklist**：
- ☐ 20-50 个真实 task 起步
- ☐ 每个 task 有 reference solution
- ☐ 多 trial（k≥3）
- ☐ Stable environment（每个 trial 干净开始）
- ☐ Grader 组合（code + model + 偶尔 human）
- ☐ 测"应该做"+"不应该做"两个方向
- ☐ Transcript viewer
- ☐ Saturation 监控
- ☐ 团队 ownership（不要"AI team 写"——产品团队写）

---

## 7. Grader 反模式：这些坑都踩过

**Anthropic 给的两个真实 case**：

### Opus 4.5 在 CORE-Bench 一开始 42%
- **bug 1**：grader rigid 到 `96.12 ≠ 96.124991...`——数字格式 vs 精度。
- **bug 2**：task spec 歧义——agent 不知道该做什么。
- **bug 3**：stochastic task 没法精确复现。
- **修复后**：Opus 4.5 → 95%。

### METR time horizon benchmark 反向激励
- **task 要求 agent 优化到 stated threshold**，但 **grader 要求 exceed threshold**。
- **遵守指令的 Claude 反而被罚分**，忽略 stated goal 的模型拿高分。

**面试可讲的角度**：**Eval 错不是 fail，是 silent reward hacking**——agent 不是按"你想要什么"优化，是按"grader 测什么"优化。

**工程落地 checklist**：
- ☐ **每个 eval task 跑 3 个不同 model**——看是否有 model 表现"反常"（高分但产物不像好的）。
- ☐ **数字格式宽容**——regex 配 fuzzy match，不是 `==`。
- ☐ **grader 不应假设 instruction 的某一具体解读**——两个独立 expert 都觉得 pass 才行。
- ☐ **让 agent 难以 hack**——task + grader 必须设计成"真解决问题才能 pass"。

---

## 8. Swiss Cheese Model：评测 + 监控 + A/B + 反馈

**Anthropic 的多层监控**（安全工程的 Swiss Cheese）：

| 方法 | 用法 |
|---|---|
| **Automated evals** | pre-launch / CI / CD / 模型升级 first line |
| **Production monitoring** | post-launch，detection of distribution drift |
| **A/B testing** | 有 traffic 后验证 significant change |
| **User feedback** | 持续 triage + sample transcript 每周 review |
| **Manual transcript review** | 校准 LLM judge，建"好"的直觉 |
| **Systematic human studies** | 校准主观输出（legal / medical / finance） |

**核心论点**：**任何一层都会漏，**多层叠加才能补上。**自动化 eval 是快速迭代 + 模型升级的 first line；生产监控是 ground truth；human review 是 calibration**。

**工程落地**：
- **每层必须有**，不能省——尤其 production monitoring 是兜底。
- **每周抽 5-10 个 transcript 看**——不做这个，LLM judge drift 到你都没发现。
- **Systematic human study 别省**——subjective 任务的金标准就是 human consensus。

---

## 一句话总结

Agent 评测不是"写几个 test case"——**它是产品需求的 executable form**。**早开始、组合 grader、测 outcome 不测 path、定期读 transcript、监控 saturation、多层监控叠加**——做好这 6 件事，Agent 团队就能从"flying blind"变成"test-driven"。

## 配套阅读

- **同主题**：ai-resistant-eval-design — AI 变强后怎么保持面试题的信号
- **评测视角**：eval-and-observability-patterns — observability + eval 的全栈监控
- **执行机制**：claude-agent-sdk-engineering — eval harness 怎么落地

参考资料：

- [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) — Mikaela Grace et al., Anthropic
- [Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) — agent 架构 vs eval 设计的耦合
- [Harbor](https://github.com/laude-institute/harbor) — 容器化 eval 框架，Terminal-Bench 2.0 跑在上面