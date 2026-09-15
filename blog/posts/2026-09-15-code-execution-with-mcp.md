---
title: Code Execution with MCP：把 MCP 当代码 API 而不是工具调用的 5 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, MCP, Code Execution]
summary: 把 Anthropic Code Execution with MCP 工程文章拆成 5 个工程模式：MCP 当代码 API 而非工具调用（节省 98.7% token）、文件系统渐进披露、代码里 filter 替代 context 污染、Privacy-Preserving PII Tokenization、State 持久化与 Skills 复用。每个模式给定位 + 代码 + 落地边界。
source-url: https://www.anthropic.com/engineering/code-execution-with-mcp
source-title: Code execution with MCP
source-author: Adam Jones, Conor Kelly (Anthropic)
---

## 引子

MCP（Model Context Protocol）已经是 Agent 接外部系统的 de-facto 标准，但**接多了就崩**——一个 5 server 的 setup 就能吞 150K token context。Anthropic 这篇解法是**把 MCP server 表达成文件系统里的代码**——每个工具一个 `.ts` 文件，Claude 写 Python/TS 调工具，**只有 stdout 进 context**。**token 节省 98.7%（150K → 2K）**。

这个想法是软件工程的经典招式：**LLM 擅长写代码，让它用熟悉的工程抽象和工具交互**——别逼它用自然语言 tool call 写循环。下面拆 5 个工程模式。

---

## 1. 把 MCP 表达成文件树：Code API 替代 Tool Call

**一行定位**：**不要 `TOOL CALL: gdrive.getDocument(...)`**——**`import * as gdrive from './servers/google-drive'`**，**让 Claude 写代码调 MCP**。

**传统方式的痛点**：
- Tool def 全 upfront 进 context（150K token）。
- 中间结果每次回 context（2 小时会议 transcript 50K token 走两遍）。

**Code execution 方式**：
- 每个 MCP server 一个目录，每个 tool 一个 `.ts` 文件：

```typescript
// ./servers/google-drive/getDocument.ts
import { callMCPTool } from "../../../client.js";

interface GetDocumentInput { documentId: string; }
interface GetDocumentResponse { content: string; }

export async function getDocument(input: GetDocumentInput): Promise<GetDocumentResponse> {
  return callMCPTool<GetDocumentResponse>('google_drive__get_document', input);
}
```

- Claude 写代码：

```typescript
import * as gdrive from './servers/google-drive';
import * as salesforce from './servers/salesforce';

const transcript = (await gdrive.getDocument({ documentId: 'abc123' })).content;
await salesforce.updateRecord({
  objectType: 'SalesMeeting',
  recordId: '00Q5f000001abcXYZ',
  data: { Notes: transcript }
});
```

- **Token 节省 98.7%**（150K → 2K）。

**面试可讲的角度**：这是 *filesystem as API*——**Linux 把所有 IO 抽象成文件，MCP 也把 tool 抽象成文件**。同样思想：让 Claude 用熟悉的编程模型（import / await）操作，而不是新的 protocol。

**工程落地**：
- ☐ MCP server > 10 个工具 → 必上 code execution
- ☐ 工具调用之间需要数据传递 → 必上 code execution
- ☐ 工具会返回大 payload → 必上 code execution
- ☐ 简单的单工具调用 → 直接 tool call，**不要硬上 code execution**

---

## 2. 渐进披露：让 Claude 走文件系统找工具

**一行定位**：**不要把工具定义全塞 context**——让 Claude **用 `ls ./servers/` 自己找**。

**两种 progress disclosure 模式**：

### 模式 A：文件系统 navigation

```
servers/
├── google-drive/
│   ├── getDocument.ts
│   ├── listFiles.ts
│   └── index.ts
├── salesforce/
│   ├── updateRecord.ts
│   └── index.ts
└── ...
```

Claude 探索：`ls ./servers/` → 发现 server → 读 `index.ts` 看 server 概要 → 读具体 `.ts` 文件看 tool interface。**只读它需要的**。

### 模式 B：search_tools 工具

在 server 上加一个 `search_tools(name, detail_level)`：
- `detail_level="name"`：只返回 tool 名。
- `detail_level="name+description"`：加描述。
- `detail_level="full"`：完整 schema。

Claude 搜 `"salesforce"` → 只加载相关 tool。**节省更细粒度**。

**面试可讲的角度**：这是 *progressive disclosure* 在 API 设计的应用——**类比 REST API 的 HATEOAS**：客户端按需发现能力，而不是 upfront 装所有。**LLM 的 context 是昂贵资源，必须 lazy load**。

**工程落地**：
- ☐ 给每个 server 一个 `index.ts` ——**有 README 性质的总览**，Claude 先读 index 决定要不要深挖
- ☐ `search_tools` 加 `detail_level` 参数——**name-only 默认进 context，full definition 按需取**
- ☐ Server 目录用 kebab-case 命名（`google-drive`），tool 文件用 camelCase（`getDocument.ts`）——方便 grep

---

## 3. Context-Efficient 结果：代码里 filter 替代 context 污染

**一行定位**：**不要让 10000 行 spreadsheet 进 context**——**让 Claude 在代码里 filter，log 只前 5 行**。

**Anthropic 的示例**：

```typescript
// ❌ Without code execution - all rows flow through context
TOOL CALL: gdrive.getSheet(sheetId: 'abc123')
  → returns 10,000 rows in context to filter manually

// ✅ With code execution - filter in execution environment
const allRows = await gdrive.getSheet({ sheetId: 'abc123' });
const pendingOrders = allRows.filter(row => row["Status"] === 'pending');
console.log(`Found ${pendingOrders.length} pending orders`);
console.log(pendingOrders.slice(0, 5)); // Only log first 5 for review
```

**Context 收益**：10,000 rows → 5 rows + summary。

**更复杂的场景**：
- **多源 join**：在代码里 join SQL + Sheets + CRM 数据，**只 log 聚合结果**。
- **聚合计算**：sum、avg、group by —— 一次性脚本解决。
- **extract specific fields**：从大 JSON 抽出 5 个字段。

**面试可讲的角度**：这是 *ETL > interactive query*——**大数据先在执行层做 transformation，再把结果喂给 model**。**和传统数据分析的"先 SQL 聚合再展示"是同个思想**。

**工程落地 checklist**：
- ☐ Tool 返回 > 100 行 → 在 code 里 filter，**只 print 你真正需要看的**
- ☐ Tool 返回 nested JSON → **extract 1-2 个 field 进 context** 而不是整个对象
- ☐ 多 tool 调用需要 join → **代码层 join**，不要 model 层
- ☐ 不要 `console.log()` 大对象——**会偷偷塞回 context**

---

## 4. Privacy-Preserving 操作：PII Tokenization 自动屏蔽

**一行定位**：**MCP client 拦截 PII 数据 tokenize，real data 永远不进 model context**。

**Anthropic 的示例**（敏感数据从 Sheets 流向 Salesforce）：

```typescript
const sheet = await gdrive.getSheet({ sheetId: 'abc123' });
for (const row of sheet.rows) {
  await salesforce.updateRecord({
    objectType: 'Lead',
    recordId: row.salesforceId,
    data: { Email: row.email, Phone: row.phone, Name: row.name }
  });
}
console.log(`Updated ${sheet.rows.length} leads`);
```

**MCP client 拦截数据 → tokenize**：

```typescript
// What the agent would see (if it logged sheet.rows):
[
  { salesforceId: '00Q...', email: '[EMAIL_1]', phone: '[PHONE_1]', name: '[NAME_1]' },
  { salesforceId: '00Q...', email: '[EMAIL_2]', phone: '[PHONE_2]', name: '[NAME_2]' },
  ...
]
```

**关键**：**real email / phone / name 从 Sheets 直接流到 Salesforce，**never through the model**。Model 只看到 token `[EMAIL_1]`。**数据传递时 untokenize via lookup**。

**面试可讲的角度**：这是 *data masking in ETL*——传统 ETL pipeline 在传输敏感字段时 tokenize，PII 不进 log / 不进 cache。**MCP client 做的就是这件事**。

**工程落地**：
- ☐ **定义 PII detection rules**——哪些字段是 PII（email / phone / SSN / name）→ tokenize
- ☐ **Tokenization 在 MCP client 层**——application 层不要碰 raw data
- ☐ **Untokenize 只在 tool call boundary**——数据写到 sink 时还原，**不写 model context**
- ☐ **可以加 deterministic security rules**——`Lead.Email` 只能写到 `Salesforce.Lead`，不能写到 `Slack.message`

---

## 5. State 持久化 + Skills 复用：Agent 自己 build toolbox

**一行定位**：**Agent 写的代码可以持久化成 reusable skills**——**用 SKILL.md 包装成结构化工具**。

**两层持久化**：

### 层 A：执行间持久化（短时）

```typescript
const leads = await salesforce.query({ query: 'SELECT Id, Email FROM Lead LIMIT 1000' });
const csvData = leads.map(l => `${l.Id},${l.Email}`).join('\n');
await fs.writeFile('./workspace/leads.csv', csvData);

// Later execution picks up where it left off
const saved = await fs.readFile('./workspace/leads.csv', 'utf-8');
```

Agent 把中间结果写文件，**长 workflow 可断点续传**。

### 层 B：跨任务复用（长时）

```typescript
// In ./skills/save-sheet-as-csv.ts
import * as gdrive from './servers/google-drive';
export async function saveSheetAsCsv(sheetId: string) {
  const data = await gdrive.getSheet({ sheetId });
  const csv = data.map(row => row.join(',')).join('\n');
  await fs.writeFile(`./workspace/sheet-${sheetId}.csv`, csv);
  return `./workspace/sheet-${sheetId}.csv`;
}

// Later, in any agent execution:
import { saveSheetAsCsv } from './skills/save-sheet-as-csv';
const csvPath = await saveSheetAsCsv('abc123');
```

**加 SKILL.md 就是结构化 skill**——和 Anthropic 的 Agent Skills 是同一概念（见 equipping-agents-for-the-real-world-with-agent-skills）。

**面试可讲的角度**：这是 *organic codebase growth*——**Agent 写一个 helper，下次直接 import**。**Agent 的"经验"沉淀成 codebase**，不是 prompt。这是 *self-improving agent* 的最朴素实现。

**工程落地**：
- ☐ **每次跑完检查 `./skills/`**——提炼出 reusable 的函数，包装 SKILL.md
- ☐ **Workspace 用 `./workspace/`**——和 `./servers/` `./skills/` 分开
- ☐ **Skill 必须幂等**——同一输入同一输出，否则断点续传会乱
- ☐ **定期清理**——`./workspace/` 是临时态，**别当数据库用**

---

## 落地的工程边界

**Anthropic 自己说**：code execution **有 infrastructure cost**——沙箱、资源限制、监控、安全。**不是免费午餐**。

**Trade-off 评估**：
| 维度 | Direct Tool Call | Code Execution + MCP |
|---|---|---|
| Token 成本 | 高（每 result 进 context） | 低（filter in code） |
| 延迟 | 中（model inference per call） | 低（一次推理 + 多次 code） |
| 实现复杂度 | 低 | 高（沙箱 + 文件系统） |
| 安全风险 | 中（tool 边界清晰） | 中高（执行任意代码） |
| Debug 难度 | 低（call/response 直接看） | 中（要 trace code execution） |
| 适用规模 | < 10 tools | 10+ tools / 多 MCP server |

**面试可讲的角度**：这是 *build vs buy*——**scale 小的时候 direct call 简单可控，scale 大的时候 code execution 收益明显**。**不要过早优化**——50 个 tools 之前 direct call 完全够用。

---

## 一句话总结

Code Execution with MCP 的核心思想是**让 Claude 用熟悉的代码抽象操作 MCP**，而不是逼它用 tool call 协议——**节省 98.7% context、用文件系统做 progressive disclosure、用代码 filter 替代 context 污染、用 client 层 tokenize 保护 PII、用持久化的 skills 让 Agent 自己积累 toolbox**。**这套是软件工程经典招式（filesystem API、ETL、PII masking、code reuse）在 LLM 时代的自然延续**。

## 配套阅读

- **同主题**：advanced-tool-use-three-features — Tool Search Tool + PTC 的更高层抽象
- **执行机制**：tool-use-engineering-patterns — 工具选择 / 并行调用
- **架构视角**：claude-code-sandboxing — code execution 的沙箱设计

参考资料：

- [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp) — Adam Jones, Conor Kelly, Anthropic
- [Cloudflare Code Mode](https://blog.cloudflare.com/code-mode/) — 同思想的另一实现
- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — 上下文压缩