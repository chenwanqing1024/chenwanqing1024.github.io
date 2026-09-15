---
title: Claude Agent SDK 实战：从 One-Liner 到 K8s 部署的 5 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, Agent SDK, MCP]
summary: 把 claude-cookbooks/claude_agent_sdk 目录的 9 个 notebook 提炼成 5 个工程模式：最小上手 / 生产治理 / MCP 集成 / 多 tier 部署 / 动态工作流规模化，每个模式给出一行定位 + 最小代码 + 工程踩坑提示。
source-url: https://github.com/anthropics/claude-cookbooks/tree/main/claude_agent_sdk
source-title: claude-cookbooks / claude_agent_sdk
source-author: Anthropic
---

## 引子

`claude_agent_sdk/` 目录里有 9 个 notebook，覆盖从「3 行代码跑起来」到「Kubernetes 多租户部署 + 动态编排千级子 Agent」的完整链路。它背后的产品是 [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python)——把 Claude Code 的 Agent 能力开放成 Python/Node SDK，让你能做"超越编程"的 Agent（研究、运维、客服、数据分析、安全审计……）。

这篇文章挑出 5 个最具工程杠杆的模式，按"**最小 → 生产治理 → 集成 → 部署 → 规模化**"排列。每个模式一行定位 + 最小代码 + 3 条以内工程提示。

---

## 1. 最小上手：`00_one_liner_research_agent.ipynb`

**一行定位**：用 `query()` 异步迭代，3 行代码跑起一个研究 Agent。

**最小代码**：

```python
import anyio
from claude_agent_sdk import query, ClaudeAgentOptions

async def research(question: str):
    options = ClaudeAgentOptions(
        system_prompt="You are a research analyst. Cite sources.",
        allowed_tools=["WebSearch", "Read", "Glob"],
        max_turns=10,
        max_budget_usd=2.0,   # ← 关键，防止 Agent 失控
    )
    async for msg in query(prompt=question, options=options):
        if hasattr(msg, "result"):
            return msg.result

anyio.run(research, "Compare Flink vs Paimon for a real-time lakehouse")
```

**工程提示**：

- `query()` 是无状态的；需要多轮会话就用 `ClaudeSDKClient`，session 在两次调用间持久。
- **`max_budget_usd` 是救命参数**——Agent 在生产里失控烧钱最常见的原因就是没有 budget cap。建议每个 Agent 入口都强制带一个。
- `allowed_tools` 用白名单：不要给 `*`，不要相信 system prompt 能挡住越权调用。

---

## 2. 生产治理：`01_chief_of_staff_agent.ipynb`

**一行定位**：把 Claude Code 的工程特性（hooks / subagents / plan mode / slash commands）拼成可治理的 Agent。

**最小代码**：

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

# 1. 持久指令（CLAUDE.md 等价物）
system = open("CLAUDE.md").read()   # 团队规则、合规要求

# 2. 子 Agent（不同领域专家）
options = ClaudeAgentOptions(
    system_prompt=system,
    allowed_tools=["Read", "Grep", "Glob", "Bash"],
    agents={   # ← 注册 subagent
        "data-analyst": {
            "description": "Analyze CSV/Parquet data and produce charts.",
            "prompt": "You are a data analyst.",
            "tools": ["Bash", "Read"],
        },
        "compliance-checker": {
            "description": "Review content for legal/policy compliance.",
            "prompt": "You check compliance.",
            "tools": ["Read"],
        },
    },
    hooks={   # ← 钩子：自动审计、敏感词过滤、限流
        "PreToolUse": [
            {"matcher": "Bash",
             "hooks": [block_dangerous_bash, log_to_audit_trail]}
        ],
        "PostToolUse": [
            {"matcher": "*", "hooks": [scrub_pii]}
        ],
    },
)

async with ClaudeSDKClient(options=options) as client:
    await client.query("Give me the Q3 revenue breakdown")
    async for msg in client.receive_response():
        print(msg)
```

**工程提示**：

- **Hooks 是合规审计的关键**。`PreToolUse` 在工具调用前拦——例如禁止 `rm -rf`、强制所有 Bash 命令走只读路径；`PostToolUse` 在调用后清洗——去 PII、写审计日志。
- Subagent 设计原则：**每个 subagent 只拿必要的 tool**。`data-analyst` 给 Bash+Read 没问题，给 WebFetch 就越界了。
- Plan Mode（`permission_mode="plan"`）让 Agent 先输出计划不执行——任何破坏性操作（删表、改 schema）之前强制走一次 Plan Mode 是企业落地的红线。

---

## 3. MCP 集成：`02_observability_agent.ipynb` + `03_site_reliability_agent.ipynb`

**一行定位**：用 [MCP](https://modelcontextprotocol.io) 把外部系统（Git、GitHub、Prometheus）变成 Agent 可调的工具。

**最小代码**：

```python
options = ClaudeAgentOptions(
    mcp_servers={
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_TOKEN": os.environ["GITHUB_TOKEN"]}
        },
        "prometheus": {   # 自定义 MCP server（参考 03 里的 JSON-RPC subprocess）
            "type": "stdio",
            "command": "python",
            "args": ["prom_mcp_server.py"],
        }
    },
    allowed_tools=["Read", "Grep", "mcp__github__*", "mcp__prometheus__*"],
)

# Claude 会自动发现 mcp__github__list_issues、mcp__prometheus__query 等等
```

**工程提示**：

- **`02` 是只读 MCP**——GitHub 工具集只能查、不能改。`03` 升级到读写——能改配置、重启服务、写 post-mortem。
- **从 02 → 03 的跳跃是生产化的关键里程碑**。一旦 Agent 有了写权限，**必须配套 PreToolUse hook 做白名单校验**（参考 03 的 `pool_size` 范围检查、`config_sanity_check`）。
- MCP server 选型：能用现成就别自己写（GitHub、Slack、Postgres、Prometheus 都有官方/社区 server）。自己写的 MCP server 用 `mcp` Python SDK 起 stdio 进程，参考 03 的 `site_reliability_agent/`。

---

## 4. 多 tier 部署：`07_hosting_the_agent.ipynb`

**一行定位**：同一个 Agent 镜像，通过 Docker / Modal / Kubernetes 三档升级，HTTP 接口保持不变。

**最小代码**（FastAPI 暴露 Agent）：

```python
from fastapi import FastAPI
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

app = FastAPI()
options = ClaudeAgentOptions(allowed_tools=["WebSearch", "Read"], max_budget_usd=1.0)

@app.post("/ask")
async def ask(q: str):
    async with ClaudeSDKClient(options=options) as client:
        await client.query(q)
        async for msg in client.receive_response():
            if hasattr(msg, "result"):
                return {"answer": msg.result}

# Dockerfile（同一个镜像，三档部署都用）：
#   FROM python:3.12-slim
#   COPY . /app && RUN pip install -r /app/requirements.txt
#   CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**三档升级路径**：

| Tier | 适用 | 复杂度 | 隔离 |
|---|---|---|---|
| **Docker（单 VM）** | 开发 / 内部工具 / 单租户 | 低 | 进程级 |
| **Modal（托管 serverless）** | 中小规模生产 / scale-to-zero | 中 | 容器级 + 自动休眠 |
| **Kubernetes（自托管）** | 多租户 / 大规模 / 合规要求 | 高 | Namespace + NetworkPolicy |

**工程提示**：

- 镜像里**不要**带 `ANTHROPIC_API_KEY`——用 secret manager 注入（K8s Secret / Modal Secret）。
- Modal 适合**偶发性 Agent 任务**（夜间跑报告、低频运维巡检），scale-to-zero 省 90% 成本。
- K8s 多租户时按 `tenant_id` 分 namespace；Agent 的 `working_dir` 必须落在 emptyDir，不能挂 PV——避免跨租户数据泄漏。

---

## 5. 动态工作流规模化：`08_dynamic_workflows.ipynb`

**一行定位**：突破单 context 窗口——让 Claude 写一段 JS 编排脚本，runtime 在千级子 Agent 上并行执行。

**最小代码**：

```python
options = ClaudeAgentOptions(
    workflow_tool={"enabled": True},   # 注册 Workflow 工具
    allowed_tools=["WebSearch", "Read", "Workflow"],
    max_budget_usd=20.0,
)

# Claude 生成的 orchestration 脚本大致长这样：
#   const reports = await parallel([
#     agent("research-A", { topic: "flink" }),
#     agent("research-B", { topic: "paimon" }),
#     agent("research-C", { topic: "iceberg" }),
#   ]);
#   const verified = await parallel(reports.map(r =>
#     agent("verifier", { claim: r, adversary: "skeptic" })
#   ));
#   return pipeline([
#     synthesize(verified),
#     format("markdown"),
#   ]);
```

**工程提示**：

- **范式判断**：如果你要在多 context 之间编排，用 workflow（确定性脚本持有 plan）；如果只在单 context 内迭代，用 subagents（模型自己持有 plan）。
- **`fan-out + 对抗验证`**是规模化关键：每个 claim 派一个 verifier 和一个 skeptic 同时跑，只有双方共识才采纳——把幻觉率砍掉一个数量级。
- 编排脚本要**只读不写**：Claude 不能直接调用 mutating 工具，必须通过 workflow runtime。runtime 端做权限边界。

---

## 落地清单：按项目阶段选

| 阶段 | 优先模式 | 解决的问题 |
|---|---|---|
| 第一个 Agent | #1 one-liner | 验证可行性 + budget cap |
| 加治理 | #2 chief-of-staff | hooks + subagents + plan mode |
| 接外部系统 | #3 MCP（02 先只读） | GitHub / Prometheus / DB 集成 |
| 上生产 | #4 Docker → Modal | 容器化 + 弹性 |
| 规模化 | #3 MCP 升级 03 读写、#5 动态工作流 | 多 subagent 并行 |
| 多租户 / 合规 | #4 K8s + #2 hooks 强化 | 隔离 + 审计 |

## 配套阅读

- **执行机制底层**：[tool_use 7 个模式](blog/posts/2026-09-15-tool-use-engineering-patterns.md) — SDK 的 `query()` / `ClaudeSDKClient` 都建立在 tool_use 之上
- **抽象层级**：patterns/agents — SDK 给的是工具，patterns 给的是模式语言（编排 / 评估 / 异步）
- **第三方服务**：third_party/Pinecone 或 MongoDB — 给 RAG Agent 接向量库

参考资料：

- [claude_agent_sdk 目录](https://github.com/anthropics/claude-cookbooks/tree/main/claude_agent_sdk)
- [Claude Agent SDK Python](https://github.com/anthropics/claude-agent-sdk-python)
- [Model Context Protocol](https://modelcontextprotocol.io)