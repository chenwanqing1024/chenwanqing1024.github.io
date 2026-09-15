---
title: "读文笔记：Flink ClickHouse Sink 的生产级攒批与动态表结构"
date: 2026-09-15
tags: [Flink, ClickHouse, 数据集成, 流计算, 后端]
summary: "得物技术把 flink-connector-jdbc 写入 ClickHouse 的三个生产痛点（无数据量攒批、固定表结构、分布式表热点）拆开重写：metaSize+timeout 双触发、本地表直写、ClusterIpsUtils 动态发现节点；并用 Checkpoint 配合两种语义（UnexceptionableSink vs ExceptionsThrowableSink）覆盖 At-Most-Once 与 At-Least-Once 两种业务诉求。"
source-url: "https://xie.infoq.cn/article/7e8c560b03aa3ba25bb1b3fea"
source-title: "Flink ClickHouse Sink：生产级高可用写入方案｜得物技术"
source-author: 得物技术
---

## 原文在说什么

得物技术把生产环境跑了一年多的 Flink → ClickHouse 写入链路开源化（虽然名义上是公司内部组件），把官方 `flink-connector-jdbc` 在 ClickHouse 场景下的三个生产痛点拆开重写。全文 1.7 万字，配了大量代码片段，覆盖从攒批机制、节点发现、限流、重试到 Checkpoint 语义的完整链路。

**痛点一：没有基于数据量的攒批。**官方 `JdbcSink.invoke()` 只在 `bufferedValues.size() >= batchSize` 时 flush，而 ClickHouse 是按 part 写入吞吐量优化的，记录数 10000 行的批次，字节量可能差 100 倍。文中给的生产配置是 `maxFlushBufferSize = 104857600`（100 MB，对应字节数）+ `timeoutSec = 30`，并在 timeout 上加 10% `SecureRandom` 抖动，避免多个 TM 同时 flush 引发惊群。`ClickHouseSinkCounter` 内部维护 `metaSize`（累计字节数）和 `values`（记录列表），`add()` 时累加、`copyValuesAndClear()` 时 `List.copyOf` 做不可变深拷贝。

**痛点二：固定表结构。**官方 Sink 把 INSERT SQL 在构造时硬编码，跨应用多表场景没法用。得物抽了 `ClickHouseShardStrategy<T>` 抽象，日志场景的 `LogClickHouseShardStrategy` 把 `application="order-service"` 映射到 `tb_logs_order_service`。缓冲区变成 `ConcurrentHashMap<String, ClickHouseSinkCounter>`，按 application 分组独立攒批，flush 时把整个 application 的 buffer 深拷贝后塞进写入队列。

**痛点三：分布式表的二次转发热点。**ClickHouse 的 `Distributed` 表会把写入转发到 shard 节点，热点行（比如同一 application）的写入会全打到同一个节点。得物改为直写本地表（`INSERT INTO tb_logs_local`），节点列表从 `system.clusters` 动态拉取：节点变更用 `AtomicBoolean IP_CHANGING` CAS 避免并发更新，节点剔除从 Redis + APM 双源拉取异常节点列表，并随机 shuffle 后选择节点避免热点。`ClusterIpsUtils` 用 Guava `LoadingCache` 维护两套缓存——clusterIpsCache 1 小时刷新（节点列表）、exceptIpsCache 1 分钟刷新（异常节点）。

**Checkpoint 语义两套。**`UnexceptionableSink`（At-Most-Once）只 buffer 不检查 Future；`ExceptionsThrowableSink`（At-Least-Once）每次 put 都 `assertFuturesNotFailedYet()`。`ClickHouseSinkScheduledCheckerAndCleaner` 用 `volatile boolean isFlushing` + `synchronized` 解决 Cleaner 线程和 Checkpoint flush 的并发冲突——Checkpoint 期间 `isFlushing=true`，Cleaner 线程直接 `return` 跳过。CheckpointTimeout 建议大于 `FutureTimeout * MaxRetries`（文章给的是 10 分钟 vs 3 分钟 × 10 次重试）。

**写入限流。**`ClickHouseWriter` 用 `LinkedBlockingQueue(10)` 做有界队列，`put()` 满时阻塞实现背压；`numWriters=10` 的固定线程池消费队列，每个 `WriterTask` 用 `CompletableFuture.orTimeout(3, MINUTES)` 防止永久阻塞。

**重试策略。**递归重试而非队列重试：失败时 `handleUnsuccessfulResponse` 把失败节点加入 `exceptHosts` 后递归调用 `send`，避开故障节点；达到 `maxRetries=10` 后 `future.completeExceptionally` 标记失败。错误码 210/1002 自动加入黑名单。

**HikariCP 调优。**`connectionTimeout=30000`、`maximumPoolSize=20`、`minimumIdle=2`、`socket_timeout=180000`（3 分钟）、`http_connection_provider=APACHE_HTTP_CLIENT`。

文中给的生产指标是百万级 TPS 日志写入。

## 我的看法

**我认同：** 这篇文章最大的价值是把"ClickHouse 不是 MySQL"这件事讲透了。MySQL 的写入是按行处理的，Flink JDBC Sink 的固定 `batchSize` 模型搬过来完全不对路。ClickHouse 是按 part 写入的，攒批的真正单位是字节而不是条数，这是整篇文章所有设计的起点。把这一个点理解了，其他设计（metaSize 累加、动态分表、本地表直写）就都是顺水推舟。

**这篇文章给我最有价值的不是具体代码，而是"两个语义模型共存"这个产品决策。** 同样是 Flink → ClickHouse 链路，日志场景允许丢（At-Most-Once + UnexceptionableSink），订单事件不允许丢（At-Least-Once + ExceptionsThrowableSink）。同一套攒批基础设施，靠 `ignoringClickHouseSendingExceptionEnabled` 一个开关切换 Sink 实现，运营和工程都不需要改业务代码。这比"做一个统一的 Exactly-Once Sink"诚实得多——因为 Exactly-Once 在跨系统写入场景下本身就是个伪命题。

**反直觉的工程判断：**

1. **加 10% 随机抖动在 timeout 上是必要的，不是过度工程。** 一旦多个 Flink TM 在同一时间点 flush，CH 集群会出现 30 秒一次的写入毛刺；分散到 ±3 秒后毛刺被吸收。这个细节一般工程师不会想到，但放在分布式系统里就是经典的"雪崩预防"。

2. **写本地表而不是分布式表，意味着客户端必须做节点发现和剔除。** 把分布式表的"转发逻辑"挪到客户端，看似增加复杂度，实则避免了热点行的转发放大效应——一个 application 在 Distributed 表下永远是同一节点接收，写本地表后被随机分散到所有节点。这个 trade-off 是"客户端复杂度换服务端热点消除"。

3. **`CompletableFuture` + `final completeExceptionally` 是必须的，不是"防御式编程"。** Future 在异常路径下如果不被显式完成，下游 `waitUntilAllFuturesDone` 会无限等。得物专门在 finally 里检查 `!future.isDone()` 兜底，这是踩过坑才能写出来的代码。没有这个兜底，Checkpoint 会一直卡住直到上游 TM OOM。

**但我有 push back：**

1. **百万级 TPS 是写入指标，但没给出 P99/P999 延迟。** 攒批的本质是把单条延迟换成批量吞吐——`timeoutSec=30s` 的设定意味着最坏情况下单条延迟 30 秒。这个数字对运营大盘类查询无所谓，对"实时反作弊"这类场景就不可接受。文章缺一个"什么场景不能这么配"的边界讨论。

2. **节点发现 1 小时刷新 + 异常节点 1 分钟刷新，事故切换时间在分钟级。** ClickHouse 集群扩缩容场景下，新节点最多 1 小时才被 Sink 识别——对于弹性集群来说太慢。文中没讨论"扩容触发主动 reload"的钩子设计，比如用 etcd watch 或 Consul 通知替代 1 小时 polling。

3. **没有给任何 backpressure（背压）传导路径的实测数据。** `LinkedBlockingQueue(10)` 满后 `put()` 会阻塞，进而阻塞 TM 的 Netty 线程。`numWriters=10` 的线程池打满后，Flink 的 checkpoint barrier 也会卡住——这是一个隐性的 TM OOM 风险。文章只在文字里提到"背压传导"四个字，没有量化数据。

### 怎么落到 Agent 项目

面试被问"如何把 ClickHouse 接入 AI 实时决策"时的回答框架：

- **数据接入模块：** Flink + ClickHouseLocalWriter + metaSize 攒批，按应用名做 `ClickHouseShardStrategy`，实测单 TM 写 5 万 TPS；用 `List.copyOf` 做不可变深拷贝避免并发修改；
- **节点发现模块：** `ClusterIpsUtils` 拉 `system.clusters`（1 小时 Guava refresh）+ Redis 异常列表（1 分钟 refresh），`AtomicBoolean IP_CHANGING` CAS 锁保护并发更新；
- **语义开关模块：** `ignoringClickHouseSendingExceptionEnabled` 切换 At-Most-Once / At-Least-Once，对应监控/告警/反作弊三类场景；底层统一 `ClickHouseWriter` + 攒批基础设施；
- **Checkpoint 协调模块：** `volatile isFlushing` + `synchronized` 解决 Cleaner 与 flush 冲突，CheckpointTimeout = FutureTimeout × MaxRetries（10 分钟 vs 3 分钟 × 10 次）；
- **运维保障模块：** 节点扩缩容触发主动 reload（用 etcd watch 替代 1 小时 polling）、P99 延迟监控、queue 长度告警、Future 永久阻塞兜底（finally 里 `completeExceptionally`）。

## 一句话总结

ClickHouse Sink 的工程问题不是"能不能写进去"，而是"按字节攒批、本地表直写、节点动态剔除、Checkpoint 语义分轨"四件事都做对——这就是得物把官方 JDBC Sink 拆开重写的原因。
