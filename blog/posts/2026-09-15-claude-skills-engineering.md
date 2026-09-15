---
title: Claude Skills 实战：让 Claude 生成 Excel / PPT / PDF 的 6 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, Skills, Agent]
summary: 把 claude-cookbooks/skills 的 3 个 notebook + 3 个 custom skill 提炼成 6 个工程模式：内置 Skill 调用 / Container+Code Execution / Files API 下载 / Custom Skill 编写 / 渐进式加载 / 多 Skill 组合。每个模式一行定位 + 最小代码 + 工程踩坑提示。
source-url: https://github.com/anthropics/claude-cookbooks/tree/main/skills
source-title: claude-cookbooks / skills
source-author: Anthropic
---

## 引子

`skills/` 是 claude-cookbooks 里**最"产品向"**的目录：3 个 notebook（基础 / 金融场景 / 自定义）+ 3 个完整 custom skill（金融建模 / 财务分析 / 品牌规范）+ 真实的样例数据集。它解决的问题不是"调工具"——而是**让 Claude 学会一种"专业能力"**，并以渐进式加载的方式按需使用。

Skills 是 Anthropic 在 2025-10 推出的产品形态，可以理解为「**装满指令、脚本、资源的文件夹**」：Claude 看到 SKILL.md 的 frontmatter 时只读 name+description（占 token 极少），判定相关后才加载完整指令，再按需调里面的 Python 脚本。**这是当前所有 LLM 产品形态里"按 token 付费"最友好的一种**——多装技能不烧钱。

这篇文章把它拆成 6 个相互独立的工程模式，按"**调用 → 闭环 → 下载 → 自定义 → 经济学 → 组合**"排列。每个模式配一行定位 + 最小代码 + 2-3 条工程踩坑提示。

---

## 1. 内置 Skill 调用：xlsx / pptx / pdf / docx

**一行定位**：用 `client.beta.messages.create` 的 `container.skills` 把官方技能挂上去，Claude 自动获得对应格式的"专家级"生成能力。

**最小代码**：

```python
from anthropic import Anthropic

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

resp = client.beta.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    container={
        "skills": [
            {"type": "anthropic", "skill_id": "xlsx", "version": "latest"}
        ]
    },
    tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
    messages=[{
        "role": "user",
        "content": "Create a monthly budget Excel with income/expense/savings, currency format, column chart"
    }],
    betas=["code-execution-2025-08-25", "files-api-2025-04-14", "skills-2025-10-02"],
)
```

**工程提示**：

- 4 个内置 Skill ID：`xlsx` / `pptx` / `pdf` / `docx`。**用 `"version": "latest"`**——Anthropic 维护升级，**别 pin 死版本**，否则错失 bug fix。
- Skills 必须挂 `code_execution` 工具，否则会报 `BadRequestError`。这是强制依赖关系，不是可选。
- **生成耗时**：Excel 约 2 分钟、PowerPoint 1-2 分钟、PDF 40-60 秒。生产环境要加 timeout + 重试，不要按普通 messages API 的 SLA 设计。

---

## 2. Container + Code Execution：最小闭环

**一行定位**：把 Skills、代码执行、文件生成三件套装进一个**沙箱 container**，Claude 在里面跑 Python 写文件，回灌 file_id。

**最小代码**（复用 container 提效）：

```python
# 第一次调用：建 container + 加载 skill
resp1 = client.beta.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    container={"skills": [{"type": "anthropic", "skill_id": "xlsx",
                           "version": "latest"}]},
    tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
    messages=[{"role":"user","content":"创建 Q1 财报 Excel：营收 100M、毛利 40M、运营成本 20M"}],
    betas=["code-execution-2025-08-25", "files-api-2025-04-14", "skills-2025-10-02"],
)
container_id = resp1.container.id   # ← 关键：保留这个 id

# 第二次调用：复用同一个 container（skill 不重新加载，节省 ~3000 token）
resp2 = client.beta.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    container=container_id,   # ← 直接传字符串 id
    messages=[{"role":"user","content":"再加一页 sheet 画营收环比图"}],
    betas=["code-execution-2025-08-25", "files-api-2025-04-14", "skills-2025-10-02"],
)
```

**工程提示**：

- **复用 container = 复用沙箱 + 复用 skill 加载状态**。第二次起只需 50-100 token 的 skill metadata，**省 99% 的 skill 加载开销**。
- container 不传 → 每次新建沙箱（冷启动 30 秒+）。**多轮对话一定要传 id**。
- container 有 TTL，过期要重建。生产里把 container_id 存 Redis，TTL 通常 1 小时。

---

## 3. Files API 下载：file_id → 本地文件

**一行定位**：Skill 在沙箱里生成的文件，response 里只能拿到 `file_id`——必须用 `client.beta.files.download` 拉到本地。

**最小代码**：

```python
# file_id 从 bash_code_execution_tool_result.content.content[0].file_id 取
# 推荐用 cookbook 提供的 file_utils.extract_file_ids() 自动解析

# 下载文件（二进制）
content = client.beta.files.download(file_id="file_abc123...")
with open("outputs/q1_report.xlsx", "wb") as f:
    f.write(content.read())   # ⚠️ 用 .read()，不是 .content

# 查元信息
info = client.beta.files.retrieve_metadata(file_id="file_abc123...")
print(f"{info.filename} | {info.size_bytes} bytes")  # ⚠️ size_bytes 不是 size

# 列出所有文件
for f in client.beta.files.list().data:
    print(f"{f.filename} | {f.created_at}")
```

**工程提示**：

- **file_id 是临时的**。下载要立刻做，不要假设能"过会再拉"——Anthropic 端有 lifetime 限制。
- **`.read()` vs `.content`**：beta files 返回的是 `BinaryAPIResponse`，**只有 `.read()`**，调 `.content` 直接 AttributeError。
- **`size_bytes` vs `size`**：metadata 字段叫 `size_bytes`，写 `info.size` 也会 AttributeError。这是 SDK beta 期的字段名"漂移"，cookbook 的 CLAUDE.md 专门列了。
- **文件会被覆盖**：重跑同一个 cell 会 overwrite 已下载的文件（output 会标 `[overwritten]`）。生产里加时间戳防覆盖。

---

## 4. 自定义 Skill：SKILL.md + scripts + resources

**一行定位**：把自己的领域知识、helper 脚本、模板打包成一个文件夹，上传后 Claude 按 metadata 自动发现。

**最小代码**（自定义 Skill 的目录结构）：

```
my_skill/
├── SKILL.md            # 必须：YAML frontmatter + 指令正文
├── scripts/            # 可选：helper Python 脚本
│   └── processor.py
└── resources/          # 可选：模板 / 数据 / 图片
    └── template.xlsx
```

**SKILL.md frontmatter 模板**（注意 name ≤ 64 字符、description ≤ 1024 字符）：

```markdown
---
name: applying-brand-guidelines
description: This skill applies consistent corporate branding (colors, fonts, layouts) to all generated documents including Excel, PowerPoint, and PDF.
---

# Corporate Brand Guidelines Skill

## Visual Standards

### Color Palette
- Acme Blue: #0066CC (headers, primary buttons)
- Acme Navy: #003366 (text, accents)
- Success Green: #28A745 (positive metrics)
- Error Red: #DC3545 (negative values)

## Excel Standards
- Row 1 headers: Bold, White text on Acme Blue background
- Alternating rows: #F8F9FA
- Charts: primary Acme Blue, secondary Success Green

## Scripts
- `apply_brand.py`: 自动应用品牌格式到任意 docx/xlsx/pptx
- `validate_brand.py`: 校验生成的文件是否符合品牌规范
```

**工程提示**：

- **description 决定"何时被加载"**。写得越精确，召回越准——cookbook 的金融建模 skill 写"This skill provides an advanced financial modeling suite with DCF analysis, sensitivity testing, Monte Carlo simulations"，金融问答会被精准命中，技术问答不会被误召。
- **SKILL.md 正文控制在 <5k tokens**。超过会被截断，关键指令丢失。**长内容拆到 scripts/ 单独引用**。
- **scripts 是 Claude 主动调的工具**。Cookbook 的 financial-modeling skill 把 DCF 公式、敏感性分析全写成 Python，Claude 在沙箱里 `from dcf_model import *`——**比自己从零写 openpyxl 代码可靠得多**。
- **resources 是惰性数据**。模板 Excel、配色字典、术语表——Claude 只在需要时才读，**别把全部资源塞 frontmatter**。

---

## 5. 渐进式加载：Token 经济学

**一行定位**：Skills 的核心创新是"按需加载"——挂 100 个 skill 不烧 token，只有真正用到的才付费。

**对比数据**（cookbook 数据）：

| 方式 | Token 开销 | 性能 |
|---|---|---|
| 手动指令（写在 prompt 里） | 5,000-10,000 / 请求 | 不稳定，看 prompt 写得如何 |
| Skills（只挂 metadata） | ~100 / 请求 | 专家级（skill 加载后） |
| Skills（命中后完整加载） | ~5,000 / 请求（一次性） | 专家级 |

**100 个 skill 同时挂载的开销**：

```python
# 即使挂 100 个 skill，初始只花 100 × 64 chars name + 1024 chars description
# = ~25k token（一次性 metadata 加载）
container_skills = [
    {"type": "anthropic", "skill_id": sid, "version": "latest"}
    for sid in ["xlsx", "pptx", "pdf", "docx", ...]   # 加你自定义的
]
# Claude 只在用到时才把对应 skill 的完整指令（<5k token）+ 资源读进来
```

**工程提示**：

- **多挂不烧钱，挂错才烧钱**。一个 skill 被误召（描述太宽泛）= 多花 5k token。**写好 description 是省钱第一要务**。
- **3 层加载模型**：metadata → 完整指令 → 链接文件。**链接文件按需 fetch**，不是 skill 加载时全读。
- 估算一个生产 Agent 的 skill 开销：`Σ(每个 skill metadata) + N 次命中的完整加载`。前者摊薄、后者与使用频率相关——**高频 skill 越值得打磨**。

---

## 6. 多 Skill 组合：跨格式工作流

**一行定位**：在一个请求里挂多个 skill，Claude 自动编排——CSV → Excel → PPT → PDF 全链路一键出。

**最小代码**：

```python
resp = client.beta.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=8192,
    container={
        "skills": [
            {"type": "anthropic", "skill_id": "xlsx", "version": "latest"},
            {"type": "anthropic", "skill_id": "pptx", "version": "latest"},
            {"type": "anthropic", "skill_id": "pdf",  "version": "latest"},
            # + 你的自定义 skill
            {"type": "custom",   "skill_id": "applying-brand-guidelines",
             "version": "1759287696"},   # 自定义 skill 用 epoch timestamp
        ]
    },
    tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
    messages=[{
        "role": "user",
        "content": """读取 sample_data/financial_statements.csv，做如下输出：
1. Excel：财务比率仪表盘（含公式、图表）
2. PPT：高管汇报 5 页（含 KPI 卡片、趋势图）
3. PDF：完整年报（含品牌规范的封面、目录、分章节）
"""
    }],
    betas=["code-execution-2025-08-25", "files-api-2025-04-14", "skills-2025-10-02"],
)
```

**工程提示**：

- **多 Skill 的协同是 Claude 自动编排的**——它会决定"先做 Excel 算数据、再做 PPT 引图表、最后做 PDF 整合"。**不要在 prompt 里写死顺序**。
- **自定义 skill 和官方 skill 同等地位**。Cookbook 的 brand-guidelines skill 在多文档生成时被自动调用，保证颜色/字体一致——**这就是 skill 的真正价值：把"组织知识"打包成可复用的资产**。
- **生成耗时叠加**：3 个 skill 串行跑可能要 5-8 分钟。生产环境用 `async` + 长 timeout，**别让用户盯着 spinner**。
- 跨 Skill 输出的格式校验：xlsx skill 出的图 → pptx skill 引用 → pdf skill 整合——**全靠 Claude 内部传递**，没有标准 schema，**要写 e2e 评测**（见 §7）。

---

## 落地清单

| 场景 | 优先加入的模式 | 解决的问题 |
|---|---|---|
| 第一次用 Skill | #1 内置 Skill + #3 Files API 下载 | 跑通 + 文件落地 |
| 多轮对话 | #2 复用 container | 节省 skill 加载 token |
| 团队专属能力 | #4 自定义 Skill | 品牌 / 流程 / 领域知识沉淀 |
| Agent 高频调用 | #5 渐进式加载 | 控制 token 开销 |
| 跨格式报表 | #6 多 Skill 组合 | CSV → XLSX → PPT → PDF 链路 |
| 内部工具集成 | #2 + #4 + Files API 落 OSS | 与对象存储 / DMS 打通 |

## 选型速查

| 需求 | 推荐 skill |
|---|---|
| 数据报表 / 财务模型 | `xlsx` + `creating-financial-models`（custom） |
| 高管汇报 / 客户演示 | `pptx` + `applying-brand-guidelines`（custom） |
| 合同 / 发票 / 文档生成 | `pdf` + `analyzing-financial-statements`（custom，做数据校验） |
| Word 文档（合同 / 报告） | `docx` |
| 公司全格式一致 | `applying-brand-guidelines`（custom）+ 任意 1+ 内置 skill |

## 与其它模式的关系

- **Skills vs Tool Use**：Tool Use 是"调单个函数"（低层次），Skills 是"装一个专家包"（高层次）。**Skills 内部通常用 code_execution 实现，code_execution 本身是 tool**。
- **Skills vs MCP**：MCP 把外部服务（GitHub / Slack）变成 tool；Skills 把"领域能力 + 脚本"打包成可加载资产。**两者正交**：MCP 用于"对接外部系统"，Skills 用于"沉淀内部知识"。
- **Skills vs Agent SDK**：Agent SDK 管"多步骤编排 + 治理"，Skills 管"单步专业能力"。**复杂 Agent 里每个 subagent 可以挂不同 skill**——例如 research Agent 挂 web-search skill，finance Agent 挂 financial-modeling skill。
- **Skills 与 prompt caching 兼容**：Skill metadata 一次性加载进 cache，重复使用 0 成本。配合 cache_control 节省 token 是天然组合。

参考资料：

- [claude-cookbooks/skills](https://github.com/anthropics/claude-cookbooks/tree/main/skills)
- [Skills 官方文档](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview)
- [Skills 最佳实践](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/best-practices)
- 配套阅读：[Claude Agent SDK 5 模式](blog/posts/2026-09-15-claude-agent-sdk-engineering.md)、[Tool Use 7 模式](blog/posts/2026-09-15-tool-use-engineering-patterns.md)
