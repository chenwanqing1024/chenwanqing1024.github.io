---
title: "复用优先 Skill 三层架构：AI Coding 的工程纪律比模型能力更重要"
date: 2026-09-15
tags: [Agent, Skill, Claude Code, 工程实践, AGENTS.md]
summary: "得物技术 (魏无涯) 用 AGENTS.md + Hook + Skill 三层结构做'组件复用优先'Agent。认同'AI 适合被放进清晰流程里工作'的核心判断，但 push back 三处：AGENTS.md 容量上限没说、Hook 触发模式维护成本没量化、'流程控制器 vs 能力包'的边界没给标准。"
source-url: "https://xie.infoq.cn/article/f77e3f370a93e6b765f3606ff"
source-title: "立正请站好：一个组件复用 Skill 的工程化实践｜得物技术"
source-author: 得物技术
---

## 原文在说什么

得物技术 (作者：魏无涯) 写了一篇关于"组件复用优先 Skill"的工程化实践，**立论起点非常工程化**：组件库臃肿不是搜索问题，是思考顺序问题——AI 写代码时默认"新建一个"而不是"先查复用"，这种思维惯性的伤害是复利型的。

**核心设计：AGENTS.md + Hook + Skill 三层结构**（这是文章最有架构感的部分）：

| 层 | 职责 | 解决的问题 | 关键实现 |
|---|---|---|---|
| **AGENTS.md** | 放基础上下文（常驻） | AI 根本不知道你有这套机制 | "组件复用优先"规则 + 组件索引入口 + 扫描后流程 |
| **Hook** | 路由增强（提高触发概率） | AI 知道有 skill，但不一定想起来用 | Claude Code 的 UserPromptSubmit + additionalContext 注入 |
| **Skill** | 提供流程和工具（真正执行） | AI 想用了，但执行过程不稳定 | SKILL.md + find-component.js 统一入口 |

**关键认知转变**：作者引用 Vercel 在 agent 评测里的发现——**AGENTS.md（被动上下文）比 Skills（主动触发）在稳定性上表现更好**。默认 skill 触发并没有提升通过率，加入显式指令后才明显改善。这把"skill 触发率低"的根因从"AI 笨"转向"agent 执行有决策成本"。

**Skill 落地的 5 个工程化细节：**

1. **统一入口收敛**：SKILL.md 明确规定 Agent 必须调用 `find-component.js`，不做"先算 scope → 查 CSV → 排序 → 补扫 → 记 usage"的分散调用。本质是把多个业务动作聚合成一个业务动作"查一下有没有可复用组件"。
2. **范围解析策略**：`resolve-scope.js` 实现"当前应用 → 根级共享 → 全量"的三层 scope fallback，不做"全仓库乱搜"。先看"我这个业务应用里有没有"，再看"全局共享有没有"。
3. **多因素加权匹配**：`match-component.js + fuzzy-match.js` 用组合评分（不只字符串包含），加 NO_MATCH_SCORE_THRESHOLD 低分阈值过滤——AI 拿到低质量候选很容易"将错就错"。
4. **索引构建流水线化**：`run-scan.js → index-manager → enrich`，不是一次性脚本。配置启用 Agent 模式，**不走规则引擎降级**，强制 Agent 完成 enrich 步骤。
5. **使用行为反馈**：`usage-tracker` 记录查找命中，团队偏好逐步学习，不需要复杂训练就能提升推荐质量。

**"让 AI 流程化"的 3 条原则**：

1. 基础上下文进 AGENTS.md（或 Hook 注入），减少 agent 决策点。
2. Skill 提供工具函数给 AI 调，不只写说明文档。find-component.js 定义固定 JSON 输出 schema（ok / matches / noMatch / scanTriggered / hint / error），提升 AI 执行稳定性。
3. 显式告诉 AI 调哪些函数，把分散逻辑聚合到一个入口。

**最后的认知转变**："写 skill 不是给 AI 增加能力，而是给 AI 增加'默认工作方式'。Skill 不只是 capability bundle，也是 workflow controller。"

## 我的看法

**我认同的核心点：流程控制器 > 能力包。** 这是文章最值的洞察。多数团队把 skill 当"工具集"，给 AI 加更多 tool、更多 function、更多 API 入口，结果 AI 还是按自己习惯乱来。**真正能让 AI 行为稳定的不是给它更多能力，是限制它的默认决策路径**——"在写代码前必须先调 find-component.js"这条规则比"我们有一个组件索引库"有效 10 倍。这跟"Code Review 比 Coding 重要"、"测试比实现重要"是一脉相承的工程哲学。

**这篇文章给我最有价值的不是三层结构本身，而是引用 Vercel 评测的"AGENTS.md 优于 Skills"那个反直觉发现。** 我们做 Agent 总以为"显式 skill 触发"比"被动上下文"高级，但 Vercel 的实验数据反过来了——**被动上下文的稳定性更高，因为 agent 不用做"要不要触发 skill"的决策**。这指向一个反直觉的设计原则：**减少 agent 的决策点，比增加 agent 的能力更影响稳定性**。这跟我做 RAG 时的经验一致——把规则写死在 system prompt，比依赖 agent 自己判断要不要调检索工具稳定得多。

**三个反直觉的工程判断：**

1. **"统一入口" > "模块化 API"。** 软件工程教科书讲模块化、高内聚低耦合，但 AI Coding 场景下完全反过来——把多个内部步骤聚合成一个外部入口（"查一下有没有可复用组件"）比暴露多个原子 API（"读索引 / 排序 / 补扫"）效果好。AI 不会漏步骤、不会搞错顺序、不会传错参数。**这是为 AI 设计的 API，不是为人设计的 API**。
2. **"NO_MATCH_SCORE_THRESHOLD" 比"召回率"更重要。** 多数推荐系统的优化目标是召回率，但 AI Coding 场景下，"AI 拿到低质量候选后将错就错"的代价远大于"漏掉一个真正可复用的组件"。宁可不召回（让 AI 新建），不要错召回（让 AI 强行复用错的组件）。阈值过滤是给 AI 用的护栏。
3. **"usage-tracker"是最便宜的反馈机制。** 不需要复杂训练，不需要强化学习，只需要"用过的组件记一笔"，就能逐步学习团队偏好。这是"用使用数据反哺推荐"的最小可行实现，比上一套 ML 系统实在得多。

**但我有 push back：**

1. **AGENTS.md 的容量上限没说。** AGENTS.md 是常驻上下文（每轮对话都加载），内容越多单次调用成本越高、越可能让 agent 注意力分散。文章说"目的不是塞满文档"，但没说实际控制在多少行 / 多少 token。团队落地时容易"加着加着就超了"，最终 AGENTS.md 变成又一个腐烂的文档。
2. **Hook 触发模式（关键词匹配"组件复用/封装组件/查组件"）的维护成本没量化。** Hook 写死了一组关键词，但 PM 和开发的实际用语会演进（"看一下老代码"、"有没有类似的功能"、"这个之前做过吗"）。关键词集合怎么维护？谁来更新？半年后会不会变成无人维护的僵尸规则？这块没说。
3. **"流程控制器 vs 能力包"的边界没给标准。** 文章最后说 skill 不只是能力包也是流程控制器，但什么时候该做能力包、什么时候该做流程控制器？标准是什么？如果团队对每个 skill 都加流程控制，会变成过度工程；如果不加，又退回到"AI 自由发挥"。这个判断标准没说清。

### 怎么落到 Agent 项目

如果让我基于这篇做一个"团队 AI Coding 规范 Agent"项目，我会拆成五个模块：

1. **AGENTS.md 规范仓库**：把团队所有"复用优先 / 命名规范 / 提交规范 / Review 规范"等基础规则收敛成结构化 Markdown 进 Git，控制单文件 ≤ 500 行，每条规则带 owner 和示例。
2. **Hook 路由层**：用 Claude Code 的 UserPromptSubmit + additionalContext 做关键词路由；关键词集合定期复盘（季度评审）；超过 50 个关键词就拆 Hook。
3. **Skill 工具集**：每个 Skill 提供统一入口 JS（如 find-component.js / check-style.js / validate-test.js），固定 JSON 输出 schema；不做模块化 API 暴露。
4. **索引流水线**：所有索引/配置类资源按"scan → manager → enrich"流水线持续维护，不做一次性脚本；启用 Agent 模式不走规则降级。
5. **usage-tracker + 反馈回路**：所有查找/调用记录使用行为，定期 review top 误召回 case，调整评分权重。

面试时的回答脚本："我做过一个 AI Coding 流程化的项目，核心是 AGENTS.md + Hook + Skill 三层架构。AGENTS.md 放基础规则（常驻上下文），Hook 做关键词路由（提高触发概率），Skill 提供统一入口的工具函数（执行稳定）。最关键的认知是'流程控制器 > 能力包'——给 AI 加 10 个 tool 不如限制它的默认决策路径。Vercel 的评测数据也支持：被动上下文的稳定性比主动 skill 触发更高，因为 agent 不用做'要不要触发'的决策。"

## 一句话总结

AI Coding 工程化的核心不是给模型更多能力，而是用规范、Hook、统一入口把 agent 的默认决策路径收窄——工程纪律比模型能力更影响产出稳定性。

## 附录：三层结构的职责分工（面试素材）

| 层 | 核心机制 | 解决的问题 | 关键工具 |
|---|---|---|---|
| AGENTS.md | 常驻上下文（每轮加载） | AI 根本不知道你有这套机制 | Markdown 规则文档 |
| Hook | 关键词路由 + 上下文注入 | AI 知道有 skill，但不一定想起来用 | UserPromptSubmit + additionalContext |
| Skill | 工具函数 + JSON 输出 schema | AI 想用了，但执行过程不稳定 | SKILL.md + find-component.js |

## 附录：5 个工程化实现细节

1. **统一入口收敛**：SKILL.md 强制 Agent 必须调 `find-component.js`，不做"先算 scope → 查 CSV → 排序 → 补扫 → 记 usage"的分散调用。
2. **范围解析策略**：`resolve-scope.js` 实现"当前应用 → 根级共享 → 全量"的三层 scope fallback，模仿人类工程师"先看我的应用有没有 → 再看全局有没有"的查找习惯。
3. **多因素加权匹配**：`match-component.js + fuzzy-match.js` 组合评分，加 `NO_MATCH_SCORE_THRESHOLD` 低分阈值过滤，避免 AI 将错就错。
4. **索引构建流水线**：`run-scan.js → index-manager → enrich`，不是一次性脚本；Agent 模式不走规则引擎降级，强制 Agent 完成 enrich。
5. **usage-tracker 反馈**：记录查找命中，逐步学习团队偏好，不需要复杂训练就能提升推荐质量。

## 附录：Vercel 实验的核心结论（反直觉发现）

- 默认 skill 触发没有提升 agent 通过率。
- 加入显式指令后明显改善。
- AGENTS.md（被动上下文）方案比 Skills（主动触发）表现更稳定。
- 原因：agent 执行有"决策成本"，被动上下文减少了 agent 的决策点。

## 附录：find-component.js 的固定 JSON 输出 schema

```json
{
  "ok": true,
  "matches": [...],
  "noMatch": [...],
  "scanTriggered": true,
  "hint": "...",
  "error": null
}
```

固定 schema 的好处：AI 拿到结构化结果后能稳定执行后续动作（直接复用 / 强制新建 / 触发扫描），不需要做"理解非结构化输出"的二次判断。
