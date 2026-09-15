---
title: "Spark UI 监控：从宏观入口到 Task 指标 — 读《深入剖析 Spark UI 界面》"
date: 2026-09-15
tags: [Spark, Spark UI, 性能调优, 数据倾斜, Shuffle, AQE]
summary: "得物技术团队对 Spark UI 全栈监控的系统性拆解：五大一级入口（Executors/Environment/Storage/SQL/Stages）、三级诊断路径（SQL→Jobs→Stages）、两个核心实战案例（scan 表慢/Shuffle 并行度不足）、关键经验公式 D/P≈M/C，以及 AQE 参数 advisoryPartitionSizeInBytes 和 coalescePartitions 调优。"
source-url: "https://xie.infoq.cn/article/1bca02621643acc15797caa7b"
source-title: "深入剖析Spark UI界面：参数与界面详解|得物技术"
source-author: 得物技术
---

## 原文在说什么

得物技术（作者硕）系统拆解了 Spark UI 监控体系的完整结构，从一级入口到二级详情、再到两个生产实战案例。

**一、五大一级入口的功能定位。** Spark UI 顶层有五个 Tab：Jobs（顶层执行概览，快速判断整体健康 + 失败定位）、Stages（Stage 粒度执行细节，性能调优核心入口）、Storage（缓存数据监控，Cached Partitions + Fraction Cached，Fraction Cached < 100% 触发内存换入换出，是 OOM 预警信号）、Environment（Spark Properties 配置检查）、Executors（资源使用 + 任务负载 + 数据分布，可识别负载不均衡 / 数据倾斜）。SQL Tab 是结构化查询的核心入口，逻辑计划 + 物理计划 + AQE 行为的"驾驶舱"。

**二、二级入口 SQL → Jobs → Stages 的递进诊断。** SQL 详情页中 Exchange / Sort / Aggregate 是硬件资源（CPU/内存/磁盘/网络）的主要消耗者。Spark UI 为这三类操作分别提供细粒度 Metrics：Exchange 的 Shuffle Write/Read 全周期指标；Sort 的 Peak memory total + Spill size total 指导 executor.memory / memory.fraction / memory.storageFraction 配置；Aggregate 同样记录 Spill + Peak memory。

**三、Stage 详情页的三大块信息。** Stage DAG（SQL 页面整体 DAG 的局部片段）、Event Timeline（分布式调度时间条带，绿色 = 计算时间，黄色/橙色 = 调度/数据交换开销）、Task Metrics（细粒度性能 + 资源数据，是所有可视化分析的底层数据）。

**四、核心经验公式 D/P ≈ M/C。** 公式含义：每个 Task 处理的数据量（D/P，D=总数据量，P=并行度）应与单个 Task 可用的计算资源（M/C，M=Executor 内存，C=CPU 核数）处于同一数量级。若 D/P 远大于 M/C → 任务过重或资源不足 → 调度排队；反之则资源浪费。

**五、关键指标 — Explosion Ratio。** 用 Spill (Memory) / Spill (Disk) 计算"数据膨胀系数"，反映单位磁盘存储对应的实际内存占用。当知道某中间数据磁盘占用即可反推内存消耗，精准评估 OOM 风险。

**六、Locality Level（本地性级别）。** 每个 Task 提交时携带 locality preference（数据所在节点/机架/任意节点），践行 Spark 的"数据不动，代码动"原则。

**七、两个实战案例。**

- **案例一（scan 表慢 + 内存问题）：** 单个 Task 处理 25MB（正常 128-256MB），原因是原始表数据量大 + 小文件太多。设置 `set spark.sql.odps.split.size.du_shucang.dws_traffic_algo_search_keyword_stats_di=512MB` 后该 Stage 快 20min。可通过减小 spark.executor.cores 核数间接增大 Task 内存，或调大 spark.executor.memory 直接增大内存。
- **案例二（Shuffle 后并行度不足）：** Join/Group 都在 Shuffle 阶段产生并行度，万能参数：
  - `spark.sql.adaptive.advisoryPartitionSizeInBytes="64MB"`
  - `spark.sql.adaptive.coalescePartitions.initialPartitionNum="1000"`
  
  当切分仍太大时，进一步：
  - `advisoryPartitionSizeInBytes="8KB"`、`minPartitionSize="8KB"`、`initialPartitionNum="3000"`

**八、内存与并行度的相互制约。** 内存一定时调大并行度 → 每个 Task 内存变小 → OOM 风险；并行度一定时调大内存 → 每个 Task 内存增大 → GC 时间增加。理想状态：Task 均衡、无 Spill、CPU 打满、内存够用。

具体算账示例：Stage 并行度 5000，参数 executor.memory=12g / executor.cores=4 / maxExecutors=250，集群最大并行度 = 250*4 = 1000，任务需分 5 批执行，每 Task 内存 3g。按经验每 Core 对应 4-8GB 内存合理，处理总并发度通常是实际并发度的 2-3 倍合理，作者迭代优化为 executor.memory=16g / executor.cores=6。

## 我的看法

**我认同：** 文章的核心论点"内存与并行度相互制约"是 Spark 调优的最朴素也最深刻的规律。文章把 Spark UI 当成一个分层的"体检报告"系统来讲解（一级入口体检、二级入口专科检查、Task 指标化验），这种类比非常工程师友好。

**这篇文章给我最有价值的不是 X，而是 Y：** 不是案例的具体参数值（这些会过时），而是 **D/P ≈ M/C 这个公式的思维方式** — 把抽象的"任务和资源匹配"翻译成一个可量化的诊断直觉。任何一个性能调优问题，你都可以套这个公式判断方向。

**反直觉的工程判断：**

1. **并行度的瓶颈不是 SQL 写得多差，是 AQE 的默认参数保守。** Spark 3.x 的 AQE 默认 advisoryPartitionSizeInBytes 是 64MB，但很多生产场景的中间数据远小于此，会导致 Shuffle 后并行度"上不去"。案例二给出的 8KB 极端值说明 — **默认值是给平均场景设计的，你的场景不是平均场景**。

2. **Executor 数量不是越多越好。** 文章里"集群最大并行度 = 250*4 = 1000，需要分 5 批执行"的算账方式反常识 — 很多人以为加大 Executor 池子能提速，但**任务批次数 = 总 Task / 并行度**是个隐藏约束。

3. **Spill 不是 Bug，是信号。** 很多人看到 Spill 就紧张，但 Spill 本身不可怕，可怕的是 Spill (Memory) / Spill (Disk) 比例失衡 — 这才是 OOM 的早期预警。

**但我有 push back：**

1. **Explosion Ratio 的"反推"假设过于理想化。** 文章说"知道磁盘占用就能反推内存消耗"，但 Spark 的内存模型（Unified Memory Management 中 Execution / Storage / User Memory 的动态争用）远比"线性反推"复杂。生产里真正决定 OOM 的是 **JVM 老年代 + G1 GC 的 Region 分配**，不是简单的内存大小。文章没说这部分。

2. **D/P ≈ M/C 公式没考虑 Shuffle 中间态。** 公式假设 D 是输入数据量，但实际 Task 内存大头往往是 Shuffle 后的中间数据 + Spill 缓冲，这两个量级远大于原始输入。文章没区分"输入 D"和"中间 D"，导致公式指导的调优可能与实际瓶颈错位。

3. **实战案例二的诚实度问题。** 作者明说"该 case 打不开了之前记录的，随便拿了一个" — 一个技术文章把"凑数"的案例放进来，会让读者怀疑前一个案例是不是也是挑选过的。Spark 调优很难有"一招制胜"的万能参数，建议作者把案例改为"我们试了 N 次才收敛"。

### 怎么落到 Agent 项目

假设让我基于这篇做一个**"Spark 性能诊断 Agent"**，会拆成五个模块：

1. **Spark UI 抓取器**：通过 History Server REST API 抓取应用全量 Metrics（Job/Stage/Task/Executor），存到时序数据库（InfluxDB / Prometheus）。
2. **指标解析层**：把 D/P、M/C、Spill (Memory) / Spill (Disk)、Locality Level 等关键指标按公式 D/P 算出诊断结论。
3. **诊断知识库**：把得物这篇的 5 大入口 + 关键参数（advisoryPartitionSizeInBytes、split.size、executor.memory、executor.cores）做成可检索的规则库。
4. **根因推理器（LLM）**：把抓取的指标 + 知识库规则喂给 LLM，让它给出"先看哪个 Tab、调哪个参数、预期收益"的诊断报告。
5. **A/B 验证闭环**：推荐参数 → 自动提交一个测试 Job → 对比前后 Stage 耗时 → 把有效调优反向更新到知识库。

**面试回答脚本：**"Spark 调优本质是'内存与并行度的匹配问题'。我在做的诊断 Agent，会把 Spark UI 的指标按 D/P ≈ M/C 这个公式自动诊断，再让 LLM 推荐 AQE 参数调优。这比人工看 UI 快 10 倍，而且能沉淀团队经验。"

**与得物原文方法的延伸对照：** 文章聚焦在 Spark 3.x 的 AQE 调优；现在 Spark 4.0 已经发布，引入了 Structured Spark Connect、新的 Adaptive Query Planner、更细粒度的 Task 调度指标。Agent 平台需要适配这些版本差异，建议采用"指标采集 + 知识库"解耦设计，让知识库随版本演进。

## 一句话总结

Spark UI 调优的本质是 **D/P ≈ M/C** — 数据量与并行度的比值必须匹配每 Task 的内存/CPU 资源；UI 是体检报告，调优是治病，关键是找到内存与并行度的平衡点。

**给面试官的延伸：** 当被追问"如果让你设计一个 Spark 监控平台"时，可以引用得物的"两级入口 + 体检报告"比喻 — 第一级是五大 Tab（Jobs/Stages/Storage/Environment/Executors + SQL）做整体指标体检，第二级是 SQL → Jobs → Stages 的递进诊断做深度专项检查。**这个分层设计比把所有指标平铺到单个 Dashboard 更人性化**，也更符合工程师从宏观到微观的认知顺序。