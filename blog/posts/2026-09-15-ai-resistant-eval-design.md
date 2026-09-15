---
title: AI-Resistant 面试设计：当模型比候选人更强，怎么保住 Signal
date: 2026-09-15
tags: [Claude, AI 工程, 面试, Eval]
summary: 把 Anthropic 性能工程团队 take-home test 三轮迭代的复盘拆成 6 个工程教训：AI 能力侵蚀面试信号的实证、为什么"禁 AI"和"抬高 bar"都不对、第一次换题失败（bank conflict 训练数据太多）、Zachtronics 风格题库胜出、Realism vs AI-Resistance 的取舍。每条给定位 + 数据 + 面试官和候选人都能用上的工程做法。
source-url: https://www.anthropic.com/engineering/AI-resistant-technical-evaluations
source-title: Designing technical evaluations that resist AI assistance
source-author: Tristan Hume (Anthropic Performance Engineering)
---

## 引子

这是 Anthropic 性能工程 lead Tristan Hume 写的一篇招聘技术复盘——不是讲模型怎么变强，是讲**当模型比你面试的候选人都强，take-home test 该怎么改**。1000+ 候选人、3 轮迭代、4 个 Claude 模型版本——整套故事的核心是一个事实：**每发一个新 Claude 模型，他们之前设计的题就被废一次**。

更值得所有面试官读的不是"他们最后用了什么题"，是**他们对"AI 能力侵蚀面试信号"这件事的应对**。下面拆成 6 个工程教训。

---

## 1. AI 能力曲线每 6 个月吃掉一档面试

**一行定位**：Claude 3.7 Sonnet 的时候 50% 候选人该把题 delegate 给 Claude；Opus 4 出来，**几乎所有 4 小时内的提交都比不过 Opus 4**；Opus 4.5 直接**和 2 小时最强人类打平**。

**Anthropic 的数据**（take-home 性能 benchmark，cycle count 越低越快）：

| 模型 / 条件 | Cycle count |
|---|---|
| Claude Opus 4（test-time compute 数小时） | 2164 |
| Claude Opus 4.5（普通 2 小时会话） | 1790 |
| Claude Opus 4.5（test-time compute 2 小时） | 1579 |
| Claude Sonnet 4.5（更久） | 1548 |
| Claude Opus 4.5（test-time compute 11.5 小时） | 1487 |
| Claude Opus 4.5（改进 harness） | 1363 |

**含义**：人类用 unlimited time 仍能打过 Opus 4.5（最佳人类 ~1363 < Opus 4.5 1363 是平手，低于它的就是人类赢）——但**有 deadline 的 take-home 早就不行了**。

**面试可讲的角度**：AI 能力曲线**比面试题迭代快**。你 2024 年设计的"难"题，2025 年就是 baseline。**任何固定题库的信号半衰期 ~12 个月**——这是新现实。

**工程落地**：
- **任何面试题都应该"过期审计"**——每年拿当年代最新模型跑一次，看是否还区分得出人类 vs 模型。
- **不要买"AI-resistant"题库**——题库是死的，模型是活的。**抗 AI 的不是题，是设计原则**（见模式 4-6）。

---

## 2. 两条路都不对：禁 AI × 抬高 bar

**一行定位**："禁止用 AI"和"必须超过 Claude Code 才能过"——**两条都会逼你失去想保留的东西**。

**Anthropic 的推理**：
- **禁 AI**：无法 enforce（remote 监考不可靠）+ 不像真实工作（工作中 AI 是允许的）。**强制禁 = 测的是"能不能不借助 AI 工作"，不是"工作能力"**。
- **抬高 bar 到"必须超过 Claude Code solo"**：人类花 50% 时间读题、build mental model，剩下时间 steer Claude Code，**永远落后于 Claude 自己**。**dominant strategy 变成"坐着看 Claude 干活"**——这又不测人类了。

**面试可讲的角度**：这是一个 *constraint satisfaction*——"区分人类" 和 "在 AI 协作下工作" 是两个 constraint，**单维设计满足不了**。

**工程落地**：
- **不要 ban AI**——除非岗位真的不用 AI。
- **不要"必须超过 AI"**——人类 + AI 协作 ≠ AI solo，**测的是协作能力，不是模型输出**。
- **第三种思路**：让 AI 用得"好"成为考核维度——prompting 质量、tooling 选择、判断何时介入。

---

## 3. 第一次换题失败：换 "in-distribution" 题没用

**一行定位**：换题不是换难度——是换"AI 训练数据覆盖程度"。**in-distribution 题目再难也会被攻破**。

**Anthropic 的踩坑**：
- 第一版 4 小时模拟器，**Opus 4 直接打过**——但还有深度可挖。
- 第二版（2 小时）改 machine feature，**Opus 4.5 也打过了**——多跑两小时 harness 还超过最佳人类。
- 第三次换题：挑了一个**真实工程问题**（2D TPU register 转置 + bank conflict avoidance）。Anthropic 自己踩过的坑——结果 Opus 4.5 **想出了他们没想到的优化**（transpose the computation 而不是 transpose the data）。把这条 hack 堵上，**再用 ultrathink 长 thinking budget，又解了**。
- **失败原因**：bank conflict / data transposition 是**整个领域公开踩过的坑**——训练数据极其丰富，**模型能从更大 toolbox 里找 trick**。

**面试可讲的角度**：*out-of-distribution* 是 AI-resistant 题目的真正定义。**模型能解是因为见过，类似问题在 pretraining corpus 里**——所以难不是关键，**不常见才是关键**。

**工程落地**：
- **搜你的题在 GitHub / LeetCode / Stack Overflow 有没有相似解**——有的话 AI 必破。
- **问"这个 trick 在哪个领域被广泛讨论过？"**——讨论越广，模型越会。
- **真独家问题需要真独家领域知识**——公司内部的某条冷门 codebase、某个新发布框架的细节、刚发生的某次事故复盘。

---

## 4. 成功之道：Zachtronics 风格——out-of-distribution 才安全

**一行定位**：**极度受限的 instruction set + 不给调试工具 + 多独立子问题**——把题变成"人类 reasoning 能 win，AI toolbox 不能 win"。

**Anthropic 的解**：
- 灵感来源：Zachtronics 的编程解谜游戏（深圳 I/O、TIS-100）。
- 设计：每题用**极小、极窄的指令集**（比如多芯片通信、每 chip 10 条指令 + 1-2 状态寄存器）。**唯一允许的解：用奇怪的方式写程序**（state 编码进 instruction pointer / branch flag）。
- **关键约束**：**不提供可视化或调试工具**。starter code 只 check 答案是否 valid。**造调试工具本身就是考点**——候选人是插 print 还是让 AI 生成 debugger，是 judgment 题。
- 多个独立子问题 → **总成绩方差小**（不会一题定生死）。

**面试可讲的角度**：这是 *testing the meta-skill, not the skill*。测的不是"你会 VLIW 优化"，是"面对一个奇怪约束系统，你怎么 reasoning"——**这种能力 in-context 学不到，模型靠 tool pattern matching 也没用**。

**工程落地**：
- **新题设计 checklist**：
  - ☐ 训练数据覆盖不到（搜不到类似 trick）
  - ☐ 多个独立子题（降低方差）
  - ☐ 没有现成调试工具（逼候选人决策）
  - ☐ 边界清晰（valid / invalid 容易判定）
- **不要追求"像真实工作"**——Anthropic 自己承认："realism 可能不再是奢侈品"——**AI-resistant 必须先于 realistic**。

---

## 5. Realism vs AI-Resistance：必须做减法

**一行定位**：**真实工作题 ≠ AI-resistant 题**。当前现实是：**为了保住 signal，你必须放弃部分 realism**。

**Anthropic 的取舍**：
- 原始 take-home 工作得很好，因为它像真实工作（性能工程师实际做的事）。
- 第二版更像真实工作（VLIW packing、SIMD），**但也更容易被 Opus 4.5 解**。
- 第三版（Zachtronics 风格）**信号强，但和真实工作关系不大**。
- Tristan 自己说：**"I'm still sad to have given up the realism"**——但**realism 是奢侈品**。

**面试可讲的角度**：这是 *fitness function conflict*。当外部环境（AI 能力）变化，**老的 fitness function（realism）必须让位**。**信号价值 > 表面真实**。

**工程落地**：
- **明确写"测试目标"**——每道题答"测的是哪项能力"，**不要写"像不像真实工作"**。
- **接受"题看起来怪"**——只要对目标能力有效。
- **多个小信号题 > 一个大综合题**——AI 难做对小信号的合谋欺骗。

---

## 6. 给面试官和候选人的双向清单

**给面试官的工程清单**：

- ☐ 每年用当年代 SOTA 模型测一次，过线就重审题库
- ☐ 题在 GitHub / Stack Overflow / LeetCode **搜不到解**
- ☐ 多独立子问题（≥3）——降低方差
- ☐ 有 hard pass / fail 阈值——不靠"整体感觉"
- ☐ 不强迫"必须超过 AI"——**测协作和 judgment，不是 solo 输出**
- ☐ 提供反馈循环——候选人做完能学到东西，不是黑盒

**给候选人的工程清单**（**给候选人当 take-home 准备时**）：

- ☐ 用 AI 工具——但**不要放弃判断**：每一步都问"为什么这样"
- ☐ Build tooling 而不是只解一次——**调试能力是考点本身**
- ☐ 留时间反思 trade-off——面试官会看注释 / commit history
- ☐ 如果题很怪（Zachtronics 风格），**别想着"标准解"**——**找到那个 weird constraint 的 weird trick**

---

## 一句话总结

当 AI 模型越来越强，**面试题的设计从"考知识 / 考 trick"变成了"考 out-of-distribution reasoning"**。你必须放弃"像真实工作"的执念，**换取"AI 难破"的安全性**。**真正的抗 AI 题不是难，是少见 + 有独立小信号 + 不给调试工具**——逼候选人 reasoning 而不是 pattern match。

## 配套阅读

- **同主题**：demystifying-evals-for-ai-agents — AI 评估 vs 人类评估的 metric 差异
- **评测视角**：eval-and-observability-patterns — 怎么测"LLM judge 自身质量"
- **执行机制**：tool-use-engineering-patterns — AI 工具协作的考核维度

参考资料：

- [Designing technical evaluations that resist AI assistance](https://www.anthropic.com/engineering/AI-resistant-technical-evaluations) — Tristan Hume, Anthropic
- [Take-home test on GitHub](https://github.com/anthropics/take-home) — 开放挑战，sub-1487 cycles 有兴趣可以投递
- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — 同样是"AI 变强后假设过期"的元话题