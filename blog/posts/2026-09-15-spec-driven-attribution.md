---
title: Spec-driven 真正值钱的不是抓 bug，是把 review 变得可追责
date: 2026-09-15
tags: [Agent, AI 治理, 工程实践]
summary: Nitin Garg 的实验砍到了骨头：spec baseline 把 review 的归因率从 0% 拉到 81%，但 recall 在统计上没动（0.525 vs 0.518）。认同他把 spec 当 governance artifact 的判断，但 push back 三处：staged generation 的"翻倍"有第二次过模型本身的 confound、5 个 reviewer 不足以撑住治理 ROI 的结论、Accountable 必须配上"被 bounced 的后果"才成立；并指出这套打法在数据湖仓里早就跑过了，spec 治理不是 AI 时代的新发明，是数据治理套了个 LLM 的壳。
source-url: https://www.infoq.com/articles/when-spec-driven-development-pays-off/
source-title: When Spec-Driven Development Pays off
source-author: Nitin Garg
---

## 原文在说什么

Nitin Garg 在 InfoQ 上发了一篇带数据的研究笔记：spec-driven development 真正值钱的不是抓更多 bug，而是把 review 变得可追责。

他用 5 个有 3–10 年经验的工程师，对两个 AI 生成的银行服务做 2×2 drift review：有 spec baseline 的条件下平均 recall 是 0.525，没有 baseline 是 0.518，p=0.69——统计上无差别。也就是说，**spec 并不能让 reviewer 多找出 bug**。但有 baseline 的一组，81% 的发现能定位到具体违反哪条命名 invariant；没有 baseline 的一组，0% 能定位，p=0.043。代价是 review 时间从 27 分钟涨到 48 分钟。

他用 90 次 LLM reviewer 复现了同一实验，attribution 也从 0.67 跳到 0.00，跨模型稳定。

更狠的是他做了一个控制实验：在简单任务上，"spec-first" 比 "直接写代码" 看起来好（59% → 92%），但 "先 reason 再写代码" 也能拿到 95%，二者差异不显著。也就是说，**简单任务上 spec-first 大部分收益是 reasoning 效应在冒充**。

最后他给了一个 targeting rule：spec 治理在"高约束、长寿命、被监管"的系统上才划算，扔掉一次性脚本。整套方法包括五个生命周期控制点 + RACI（模型 Responsible，人 Accountable）+ 对齐 EU AI Act / NIST AI RMF / ISO 42001 的合规需要。

## 我的看法

**我认同的核心点：attribution 才是真问题。** 我自己也写 agent，AI 生成的代码/Prompt/SQL 出问题时，最痛的不是"哪行错了"——是"这个行为到底是 spec 没写、AI 没看见、还是 reviewer 没看出来"。Nitin 的实验把这种痛量化成 0% vs 81% 的归因率，砍到了骨头。

把 spec 当 governance artifact 而不是 prompt 装饰，这一点我特别买账。我做 RAG 时，agent 的 tool schema 就是 spec baseline，drift detection 在边界上做，这套思路跟他一脉相承。Spec 不是为了让 AI 更聪明，是为了让"AI 错了"这件事在组织里可以被讨论、被复盘、被追责到某个人。

**但我对他的几个点要 push back。**

第一，staged generation 的"几乎翻倍"那个数据有 confound，他自己承认了——赢的那一臂跑了模型两次（先写 spec 再实现）。这意味着 staged 的收益里可能有一半来自"让模型自己复核一遍"，而不是 spec 本身。如果我重做这个实验，我会加一个 control：让模型"写一个 plan，然后从头重新写代码"，不引入任何 spec 概念，看能不能拿到差不多的提升。我怀疑能。

第二，5 个 reviewer 是个真信号但不够大。5 个人读同一份 spec，attribution 高也许不只是 spec 的功劳，可能是这群人本来就会"按清单走"。换成 50 个不同经验层级的 reviewer，attribution gap 不会消失，但可能缩。把他那个 n=5 当成"方向性证据"而不是"治理投资回报"是对的。

第三，"RACI 里人 Accountable、模型 Responsible" 在合规语言上漂亮，但在工程团队里，Accountable 必须配上"被 bounced 的后果"才成立。否则写一行字说"我负责"和真负责是两回事。如果 unattributed findings 不会被退回 author，spec 治理就只是文档体操。

**我加的例子：spec 治理不是 AI 时代的新发明。** 这套思路在数据湖仓里早就跑过了。我做 Flink + Paimon 的活儿，data contract 就是 spec baseline，schema evolution 配 lineage 就是 drift detection，DLQ + reconciliation 就是 reconciliation record。区别在于 AI 生成的代码"看起来对"的概率远高于"格式错乱的数据"，所以才需要 invariant 化的 spec baseline。

如果你的团队已经在做严格的数据契约，spec-driven AI 治理可以直接复用同一套 contract 模板；如果你的团队连 schema evolution 都还没管好，先别上 spec-driven AI 治理，把数据侧的活儿先做掉。

## 一句话总结

Spec-driven 真正值钱的是把 review 从"看着不对劲"变成"违反第几条 invariant"——但只对高约束、受监管、长寿命的系统值得付这 48 分钟的代价，简单任务上的收益大多是 reasoning 在冒充。
