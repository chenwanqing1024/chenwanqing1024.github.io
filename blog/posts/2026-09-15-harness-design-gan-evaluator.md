---
title: Harness 设计实战：Generator-Evaluator 模式的 6 个工程教训
date: 2026-09-15
tags: [Claude, AI 工程, Harness, Agent 架构]
summary: 把 Anthropic 长时 Agent Harness 设计文章拆成 6 个工程教训：Context Anxiety 与 Reset 的必要性、Self-Evaluation 偏差、GAN 启发的 Generator-Evaluator、Sprint 契约与文件 handoff、Evaluator 调优要花几轮、Harness 是活系统（每次升级模型要重审）。每个模式配定位 + 数据 + 工程落地。
source-url: https://www.anthropic.com/engineering/harness-design-long-running-apps
source-title: Harness design for long-running applications
source-author: Prithvi Rajasekaran (Anthropic Labs)
---

## 引子

Anthropic Labs 的 Prithvi Rajasekaran 写的这篇没有吹"我们做出了多牛的 Agent"——它是**怎么用一个 6 小时跑出 $200 token 成本的 harness 把一个 1 句话 prompt 变成能玩的 2D 游戏**的复盘。真正的工程遗产是 **GAN 启发的 Generator-Evaluator 三 Agent 架构**，以及一个反复出现的元教训：**harness 的每个组件都是"模型做不到 X"的假设，模型变强之后假设会过期**。

下面把它拆成 6 个工程教训，按"**问题 → 解法 → 调优 → 元教训**"递进。每个模式给定位 + 数据 + 落地做法。

---

## 1. Context Anxiety：模型在 context 满前主动收尾

**一行定位**：模型**自己判断** context 快满了，**主动 wrap up**——不真满也会提前收。

**Anthropic 的观察**：
- Sonnet 4.5 表现强烈——**context 还有空间就开始草草结束**。
- Compaction（压缩历史）**没用**——因为 anxiety 来自"我以为我要满了"，压缩不刷新这个判断。
- **Reset（清空 context + 结构化 handoff）才有效**——干净 slate 重新开始，但 handoff artifact 必须够完整，下个 agent 接得住。
- Opus 4.5 大幅缓解这个行为，所以 Opus 上 harness 可以**完全去掉 reset**。

**面试可讲的角度**：这是 LLM 的 *anchoring bias*——模型在训练时见过很多"对话快结束"的模式，会在 context 接近窗口时**模拟收尾行为**。Reset 是粗暴但有效的解，因为新 session 没这个 anchor。

**工程落地**：
- **观察你的模型有没有 anxiety**——跑 4 小时长任务，看是不是在 ~70% context 容量时输出明显变急。
- **Handoff artifact 必备字段**：当前进度 / 下一步任务 / 已知坑 / 待验证假设。**不要写历史细节**——那是给新 agent 的 context 准备的，不是它的 context 本身。
- **Compaction vs Reset 选择**：compaction 是"省钱"，reset 是"重置"。前者保留连续性，后者治 anxiety。**长任务优先 reset**。

---

## 2. Self-Evaluation 偏差：Agent 评自己永远给好评

**一行定位**：让 LLM 评自己生成的输出，**几乎必然给好评**——设计性任务尤其严重。

**Anthropic 的分析**：
- "Is this design good?" 没法 binary check。模型**逻辑上倾向 lenient**——它没理由严判自己。
- **即便有可验证结果**（代码编译过、test 通过），模型仍会"我说服自己其实还行"。
- **关键洞见**：分离 Generator 和 Evaluator 后，skepticism 更容易调优——**让"独立审稿人"挑剔比让"作者"自虐容易得多**。

**面试可讲的角度**：这是 *motivated reasoning* 的 LLM 版本。模型没有"ego"，但训练目标（helpful）让它倾向**和用户站在同一边**——而"我是 generator"这个角色就是和用户一边。**必须物理分离**才能破。

**工程落地**：
- **不要让 Generator 自评**——如果非要，加显式 prompt "你现在扮演严格的代码审查员，前 50 个 bug 找到再评价"。
- **独立 Evaluator 不共享 prompt**——Generator 的 system prompt 不能直接复用，会带 bias。
- **给 Evaluator 真实测试能力**（Playwright、bash、curl）——"看着像"和"测过了"是两个 confidence。

---

## 3. Generator-Evaluator Loop：5-15 轮迭代的 GAN 启发

**一行定位**：Generator 出一个版本，Evaluator 用工具实际操作并按 criteria 评分，反馈驱动 Generator 改进——**循环直到 plateau**。

**Anthropic 的前端设计实验**：
- 一个 prompt 生成 HTML/CSS/JS。
- Evaluator 用 Playwright MCP **实操页面**（不只是看截图），逐 criterion 评分 + 写详细 critique。
- 每轮 ~10-20 分钟，**5-15 轮迭代**，跑满可达 4 小时。
- Generator 每轮决策：分数趋势好就 refine 方向，趋势差就 pivot 整个 aesthetic。

**关键的 criteria 设计**（4 个维度）：
- **Design quality**（整体感 vs 拼凑感）——*权重高*
- **Originality**（自定义决策 vs 模板默认）——*权重高*
- **Craft**（字体、间距、对比度等技术执行）——Claude 默认就 OK
- **Functionality**（可用性）——Claude 默认就 OK

**反直觉**：刻意**多权 design + originality**，**少权 craft + functionality**。**因为模型"够好"的维度给权会浪费迭代预算**。

**面试可讲的角度**：这是 *gradient signal for LLMs*。Criteria 就是 loss function——你重视什么，模型就往哪儿使劲。**Criteria 的措辞会塑造输出方向**——文章里写"the best designs are museum quality"，模型就真的往 museum 风格收敛。

**工程落地**：
- **Criteria 必须 explicit + weighted**——模糊 criteria 给的反馈没用。
- **Evaluator 必须能实操**——只看截图/代码的 Evaluator 给的反馈不够 grounding。
- **第一轮就要超过 baseline**——只靠 criteria 措辞就能带模型离开 AI slop，**反馈循环是增量**。

---

## 4. Sprint 契约：Generator-Evaluator 在写代码前先对齐

**一行定位**：每个 sprint 开始前，**Generator 和 Evaluator 协商"什么算 done"**——用文件 handoff 固化。

**Anthropic 的全栈架构**：
- Planner：1-4 句 prompt → 完整 product spec。
- Generator：一次做一个 sprint，**每个 sprint 前先和 Evaluator 签 contract**——"这次做 X，done 的定义是 Y，可测试行为是 Z"。
- Generator 写代码，Evaluator 用 Playwright **真点页面 + 测 API + 查 DB**——按 contract criteria 评分，**任一 criteria 低于阈值 → sprint 失败**。
- **文件 handoff**：Agent 之间用文件通信，写一个、读一个。**比 message queue 更稳**——可追溯。

**为什么不直接照 spec 写**：**spec 太高层，code 太细节**——中间需要"可测试的小目标"做桥。Contract 就是桥。

**面试可讲的角度**：这是 *interface contract* 在多 Agent 系统的应用。每个 sprint 是个 sub-deliverable，contract 是它的 acceptance criteria——Agent 协作的"单元测试"。

**工程落地**：
- **Contract 写到文件**——不要只放 memory。文件可审计、可版本控制、可回放。
- **每个 criteria 必须 verifiable**——"看起来不错"不是 criteria，"Playwright 在 X 路径不报错"才是。
- **阈值要 hard**——文章里任一 criteria 失败就拒，不算 average。这是 quality gate，不是 grading rubric。

---

## 5. Evaluator 调优：要花几轮迭代才能靠谱

**一行定位**：**Out-of-the-box 的 Claude 是烂 QA**——识别了 bug 又说服自己无所谓，必须花几轮迭代调。

**Anthropic 的踩坑**：
- 早期 Evaluator 找到 legitimate bug → 说服自己 "not a big deal" → 批了。
- 测试流于表面——不探 edge case，深层 bug 漏过。
- **调优循环**：读 Evaluator 日志 → 找判断和人类不一致的 case → 改 QA prompt → 再跑。
- **Sprint 3 一个 contract 有 27 条 criteria**，Evaluator 抓出 3 处真 bug（fillRectangle 触发、Delete key condition 缺、FastAPI route 顺序导致 PUT /frames/reorder 路由到 `/{frame_id}`）。
- 抓 bug 的具体性是关键——"功能有问题"没用，"LevelEditor.tsx:892 的 condition 应是 X"才有 actionable。

**面试可讲的角度**：这是 *evaluator calibration*——LLM judge 自身的质量是工程问题。**不调就直接用的 judge，等于没 judge**。

**工程落地**：
- **建 evaluator testset**——一组已知 bug，让 Evaluator 跑一遍，看漏掉多少、误报多少。这是 F1 评分的基础。
- **Prompt 迭代必须有日志支撑**——不能凭感觉改 prompt，要看 logs 找具体错例。
- **Evaluator 的"具体性"是首要指标**——feedback 越具体（带文件:行号），generator 改起来越准。

---

## 6. Harness 是活系统：模型升级必须重审每个组件

**一行定位**：**每个 harness 组件都是"模型做不到 X"的假设**——模型升级 → 假设过期 → 必须重审。

**Anthropic 的简化故事**：
- 第一版（Opus 4.5）：Planner + Generator + Evaluator + Sprint。**Sprint 构造是为了给 Sonnet 4.5 拆任务**。
- Opus 4.6：模型能自己 sustain 长任务 → **Sprint 构造多余**。
- 实测：去掉 Sprint，**Evaluator 从 per-sprint 改成 end-of-run pass**——大多数 sprint 评了也是白评。
- 简化后 DAW 任务：4 小时 / $124，效果不变。
- **元教训**："每次新模型发布，重审 harness——剥掉不再 load-bearing 的部件，加新部件以做模型自己做不到的事"。

**面试可讲的角度**：这是 *YAGNI applied to AI infra*。**模型能力曲线比 harness 改进快得多**——今年必须写的 helper，明年可能就成了 dead weight。Harness 维护的核心工作不是"加新功能"，是"砍旧部件"。

**工程落地**：
- **每次模型升级跑 ablation**——每次去一个组件，看输出质量降不降。降了就加回来，不降就永久删。
- **Evaluator 的 value 是 conditional**——任务越靠近模型 solo 能力上限，evaluator 价值越高；越靠近 trivial 任务，evaluator 就是 cost center。**不要无条件保留**。
- **保持 harness 的可拆性**——每个 agent / 每步能独立测试、独立跳过。耦合死了的 harness 没法 ablation。

---

## 数据对比：Solo vs Harness

| 任务 | 时长 | Token 成本 | 输出质量 |
|---|---|---|---|
| Solo Claude（1 句话 prompt） | 20 min | $9 | 游戏核心玩法**坏掉**——entity 不响应输入 |
| Full Harness v1（Opus 4.5） | 6 hr | $200 | 可玩 + AI 内置辅助 + 10 sprint |
| Full Harness v2（Opus 4.6，无 sprint） | 4 hr | $124 | DAW 全功能 + 3 round QA |

**单看成本差 22x，但质量差"能不能玩"——这就是 harness 的 ROI**。

## 一句话总结

长时 Agent harness 设计的本质是**和模型能力赛跑**：今天必须显式拆任务，模型变强后拆任务就成 dead weight；今天必须独立 Evaluator，模型变强后 Evaluator 可能只在边缘 case 有价值。**好的 harness 工程师不做加法，做减法——每次新模型发布，把不再 load-bearing 的部件永久剥掉**。

## 配套阅读

- **同主题：Managed Agents 架构** — sandbox / harness / session 三层解耦
- **执行机制**：tool-use-engineering-patterns — Generator-Evaluator 的 handoff 走文件 vs 走 tool 的取舍
- **评测视角**：eval-and-observability-patterns — Evaluator 自身怎么评测

参考资料：

- [Harness design for long-running applications](https://www.anthropic.com/engineering/harness-design-long-running-apps) — Prithvi Rajasekaran, Anthropic Labs
- [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)