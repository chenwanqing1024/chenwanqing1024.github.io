---
title: "数仓 AI Coding Harness 读文笔记：把 Claude Code 改造成 95%+ 规范遵守率的护栏系统"
date: 2026-09-15
tags: [Harness, 数仓, Claude Code, Hooks, Subagent, CLAUDE.md]
summary: "得物技术 作者丹克 讲数仓场景下如何用 Claude Code 的 CLAUDE.md + Hooks + Subagent + Memory 五层防御，把 SQL 规范遵守率从 70~80% 拉到 95%+、需求一次通过率从 50% 拉到 90%、主 context compact 频率降 50~70%；核心反直觉判断：Claude Code 的 compact 不是 bug，是约束——你必须用 hooks 和 subagent 重新分配它的 context。"
source-url: "https://xie.infoq.cn/article/0b53fd5abaaf99ba96386477a"
source-title: "Claude Code Harness 工程：数仓侧落地方案｜得物技术"
source-author: 得物技术
---

## 原文在说什么

原文的核心矛盾一句话总结：**越复杂的需求越容易撑爆 context → 撑爆后 compact 触发 → 关键约束遗忘 → AI 犯低级错误。**
数仓场景下这个问题尤其尖锐：一个大型宽表需求要处理血缘查询结果（500~3000 tokens）、23 条自测 SQL 执行结果（5000~15000 tokens）、SKILL 规范文件内容（~10000 tokens）、数据比对两表样本（大量行），context 迅速膨胀。

得物离线数仓主力工具是 Claude Code，辅以数据平台 IDE 插件。痛点三类：

1. **失忆**：告知"金额字段单位是千元"，对话到一半 AI 忘了，生成的 SQL 把千元当元用，**数据差了 1000 倍**。这是 Claude Code context compact（默认 95% 触发）的系统性限制。
2. **规范执行不稳定**：OneData 命名规范、注释三段式、INSERT 必须带 PARTITION——工期紧张时人工规范遵守率降到 60%~70%，AI 靠 prompt 记忆也只有 70%~80%。
3. **复杂需求 context 撑满**：越到后期 AI 越不可靠。

围绕这些痛点，原文给出一个公式化的判断：**准确率 = 语义理解深度 × 数据规范覆盖度**。两端都是变量。Harness 的目标就是让变量变稳定。

五层防御体系（从简单到复杂）：

1. **写死进 CLAUDE.md**：项目根目录 `.claude/CLAUDE.md` 每次 compact 后从磁盘重新注入，是最可靠的持久化位置。原文给出一份样例：当前迭代状态（正在开发的表、版本、node_id、状态）、本次迭代约束（禁止修改的表、分区字段格式、amount 字段单位）、数仓全局规范（建表分区、SELECT * 禁止、DECIMAL 类型、INSERT PARTITION 子句）。**操作规则**：进入新迭代时手动更新前两节；上线后清空约束节；全局规范长期保留，控制在 100 行以内。
2. **Auto Memory 跨会话积累**：Claude 自动将跨会话发现写入 `~/.claude/projects/<project>/memory/MEMORY.md`，每次 compact 后重新注入。原文给出三个主动触发时机："这张表的 amount 字段单位是千元，请记住"；"field_a 在特定场景下会为空，请记住这个踩坑"；"本次 V1.0 的关键变更是 field_b 逻辑调整，请记住"。
3. **Hooks 自动验证（核心防御）**：在 `.claude/settings.json` 配置 `PostToolUse` hook，每次写 `.sql` 文件后确定性触发规范检查。原文给出一份完整的 `validate_sql.sh`，检查 4 类违规：`SELECT *`、INSERT 缺 `PARTITION`、DOUBLE 类型金额、UPDATE/DELETE 缺 WHERE。**关键陷阱**：阻断必须用 `exit 2`，`exit 1` 不会阻止 Claude 继续执行。另有一个 `block_dangerous_ddl.sh` 在 PreToolUse 阶段拦截 DROP/TRUNCATE 生产表（放行 `_dev/_test/_stg` 后缀）。原文还提到 `inject_context.sh` 用于 compact 后重注入上下文。
4. **Subagent 做上下文隔离**：核心原则是"高 token 消耗但结果只需要摘要"的操作放到 subagent 独立 context。原文给出两个示例：`sql-validator`（用 haiku 模型，permissionMode: dontAsk，tools: Read/Bash/Grep/Glob，只做验证，输出不超过 50 行结构化报告）和 `dw-explorer`（数仓结构探索，只读，分析一层血缘，输出不超过 80 行摘要）。主对话调用方式有两种：自然触发（"用 dw-explorer 分析 db_a.dwd_table_a 的结构"）或强制指定（`@"sql-validator (agent)" 验证 path/to/insert.sql`）。
5. **SKILL 文件改造**：当前 SKILL 文件（01~08.md）每次调用全文加载进主 context，加速 compact。改造方向——把执行步骤提炼成 subagent 指令，subagent 内部读完整 SKILL 文件，主 context 只接收结果摘要；用 path-scoped rules（`.claude/rules/etl-rules.md`，按 `paths: ["**/*insert*.sql", "**/*_di.sql", "**/*_df.sql"]` 触发）替代 SKILL 文件中的规范章节，按需加载。

数仓 8 步工作流（需求分析 → 技术设计 → ETL → 自测 → 数据比对 → SR 导入 → 性能优化 → SLA/DQC）天然对应 Harness 三层机制：需求分析、技术设计、SR 导入、SLA/DQC 在主会话处理（context 压力低）；ETL 开发靠 hook、自测/数据比对靠 subagent、性能优化靠 dw-explorer subagent。原文以 `/dw-etl` 为例，命令封装了规范内容（建表规范、INSERT OVERWRITE + PARTITION、禁止 SELECT *）、产出格式（`ddl_[表名].sql` + `insert_[表名].sql` + `ddl_sr_[表名].sql`）、自动护栏（PostToolUse hook）、subagent 卸载。

四类具体问题与解法：

| 问题 | 解法 | 效果 |
|---|---|---|
| 字段口径遗忘导致计算错误 | CLAUDE.md 注入 + Auto Memory | 从"时常发生"降到"基本不出现" |
| 需求理解偏差导致返工 | CLAUDE.md 迭代约束 + Stop hook 检查任务完整性 | 一次交付通过率 50% → 90% |
| SQL 规范执行不一致 | PostToolUse hook + `exit 2` 强制阻断 | 70%~80% → 95%+ |
| 大型需求 context 耗尽 | 血缘 / 自测 / SKILL 全部走 subagent | 主 context compact 频率降 50%~70% |

## 我的看法

**我认同**作者把"失忆"归因为"系统性的 compact 限制"而非"模型能力不足"——这是一个非常重要的视角转换。
一旦承认 compact 是约束，你就不会试图让 prompt 更聪明，而是去抢 compact 触发的窗口期：把约束写进会重新注入的 CLAUDE.md，把验证放到不依赖模型的 hooks，把高 token 操作隔离到 subagent。
这是把"软件系统"和"LLM"当成两层来设计——LLM 是会失忆的执行单元，确定性系统是不可失忆的协作底座。
我自己在做 Agent 项目时也反复印证这一点：把状态写进磁盘、把规则写进 hook、把高 token 操作下沉到 subagent，主对话的"模型智力"才能被解放出来。

**这篇文章给我最有价值的不是"五层防御体系"这个分类，而是 `exit 2` 这个细节和"高 token 操作放 subagent"这条原则。**
前者是 hook 协议里的"阻断语义"，是规范从 LLM 记忆迁移到确定性系统的关键开关；后者是 context 工程的核心动作——不是因为 subagent 更好，而是因为 subagent 的 context 不会污染主对话的 context。
这两件事单独看都不起眼，但合在一起就构成了 Harness 工程的"协议层基础"——一个 hook 协议、一个 context 隔离协议。

三个反直觉的工程判断：

1. **Compact 不是 bug，是约束**——95% 阈值是设计意图，不是缺陷。原文把 compact 当作"必须重新分配 context 的强制窗口"，写 CLAUDE.md 就是抓住这个窗口。如果团队只想着"延长 context"或者"换更长的窗口"，就抓不到根本。
2. **`exit 2` 与 `exit 1` 的区别是 hook 协议里最容易被忽略的工程细节**——后者不会阻止 Claude 继续执行。这意味着你的规范检查即便报错了也只会变成"提示"，Claude 完全可以无视。原文把这条作为"关键陷阱"列出，说明团队落地时踩过坑。
3. **Harness 的目标不是让 Claude 更聪明，而是让研发流水线更可靠**——分工明确：Claude 负责语义理解（理解需求、设计方案、生成代码），hooks 负责规范检查和拦截，subagent 负责大量读取操作，CLAUDE.md + Memory 负责跨会话持久化。这是把"AI 擅长的事"和"系统擅长的事"做了一次明确切分。

但我有 push back：

1. **`validate_sql.sh` 用 `grep -iE` 做正则检查非常脆弱**。复杂 SQL 里的字符串字面量、注释、`/* ... */` 块、`WITH ... AS (...)` 子句都会触发误报。原文没给出误报处理机制，也没说明"WARNING"与"CRITICAL"的实际阻断逻辑差异。如果 hook 频繁误报，团队会很快绕开 hook 调用 AI 直接改文件。
2. **Auto Memory 的"主动触发"对人不友好**。原文要求工程师主动说"请记住"，这等于把"记忆负担"重新压回人——这恰恰是工程师最容易忘的环节。一个更稳的方案应该是让 hook 在失败发生时自动写入 memory，而不是等工程师记得说"请记住"。如果记忆必须靠人主动写，那么 Harness 的"自动化"承诺就有缺口。
3. **"compact 频率降低 50%~70%"这个数字没有给出基线测量方法**。原文给出了目标收益，但没说怎么度量——是按"对话 token 累计"算？还是按"完成一张宽表所需的回合数"算？缺测量方法会让"harness 真的有用"这个论点无法被复现验证。

### 怎么落到 Agent 项目

如果让我基于这篇搭一个"数仓 AI Coding Harness"，我会画五个模块：

- **CLAUDE.md 模板引擎**：根据项目结构（数据库名、表名、字段类型）自动生成当前迭代约束节，上线后自动清空；规范节控制 100 行上限，超出强制归档到 path-scoped rules。
- **SQL Hook 校验套件**：基于 SQL 解析器（`sqlglot` / `sqlparse`）而不是 grep 实现检查；每个规则独立可关；WARNING 与 CRITICAL 分两套退出码，CRITICAL 才阻断。
- **Subagent 注册中心**：内置 `sql-validator`、`dw-explorer`、`data-quality-checker`、`data-comparator` 四个 subagent，每个都强制 `model: haiku` + `permissionMode: dontAsk` + 输出行数上限。
- **Memory Auto-Writer**：PostToolUse 失败时自动把"失败现象 + 修复方式"写入 MEMORY.md，避免依赖人工记忆。
- **8 步 SKILL 触发器**：`/dw-etl`、`/dw-self-test` 等命令封装 SKILL 文件全文加载到 subagent，主对话只收摘要报告。

面试如果被问"怎么把 Claude Code 用到数仓研发"，可以这样答：**承认 compact 是约束不是 bug，把约束写进 CLAUDE.md 抢窗口期；用 PostToolUse hook 强制 SQL 规范（`exit 2` 阻断语义别用错）；把高 token 操作（血缘、自测、数据比对）全部下沉到 haiku 模型的 subagent；Auto Memory 由 hook 失败时自动写入而不是靠人工记；五层分工明确，Claude 只负责语义理解，其他由确定性系统兜底。**

## 一句话总结

> 数仓 AI Coding 的瓶颈不是 Claude 不会写 SQL，而是 compact 会让约束丢失、规范会靠记忆、context 会撑爆——Harness 的本质是把"语义 × 规范 = 准确率"两边从 LLM 记忆里迁出来，交给 hooks、CLAUDE.md、subagent 各自托底。

## 延伸思考：CLAUDE.md 的 100 行上限为什么是金科玉律

CLAUDE.md 全文要在每次 compact 后重新注入，100 行上限对应的实际是"context 抢占窗口"——超长 CLAUDE.md 会反复挤占主对话可用空间，反而降低模型判断力。

所以 100 行的本质是**"对模型友好"和"对工程严谨"的平衡点**：

- 太少 → 关键约束进不来，AI 还是会失忆。
- 太多 → 每次 compact 都搬运一大段历史，挤占有效 context。
- 100 行 → 强制把"经常用的"和"偶尔用的"分开，经常用的进 CLAUDE.md，偶尔用的进 path-scoped rules 或 subagent。

这就是为什么原文把"全局规范长期保留、控制在 100 行以内"写成了一条操作规则——这不是审美，是协议。