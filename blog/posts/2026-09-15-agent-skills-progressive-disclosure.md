---
title: Agent Skills 设计：渐进披露让 Claude 按需加载专业能力的 5 个工程模式
date: 2026-09-15
tags: [Claude, AI 工程, Agent, Skills]
summary: 把 Anthropic Agent Skills 工程文章拆成 5 个工程模式：渐进披露三档（name/description → SKILL.md → 附加文件）、Skills + Code Execution 的组合、PDF skill 实战拆解、4 条 Skill 开发原则（eval-driven / structure for scale / Claude 视角 / iterate with Claude）、Skill 安全审计。配目录结构 + 面试可讲的设计取舍。
source-url: https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills
source-title: Equipping agents for the real world with Agent Skills
source-author: Barry Zhang, Keith Lazuka, Mahesh Murag (Anthropic)
---

## 引子

当 Agent 能跑在完整计算环境（filesystem + code execution）上，**问题不再是"Agent 能做什么"，而是"怎么让通用 Agent 变成特定领域专家"**。Anthropic 的解法是 **Agent Skills**——一个目录里装 SKILL.md + scripts + resources，**靠渐进披露让 Claude 按需加载**。这把"onboarding 新员工"的隐喻做成了**实际工程模式**：**新员工不用第一天读完所有手册，目录告诉他手册在哪、遇到具体问题再去查具体章节**。

下面拆 5 个工程模式，按"**架构 → 渐进披露 → 代码组合 → 开发原则 → 安全审计**"递进。

---

## 1. Skill 是什么：一个目录 + SKILL.md + 可选 resources

**一行定位**：**Skill = 装满 instructions / scripts / resources 的目录**——**SKILL.md 是入口，frontmatter 是 metadata，正文是给 Claude 的指令**。

**Skill 的目录结构**（以 PDF skill 为例）：

```
pdf-skill/
├── SKILL.md           # 入口，含 YAML frontmatter + 指令
├── forms.md           # 仅表单场景时读
├── reference.md       # 复杂场景时读
└── scripts/
    └── extract_form_fields.py   # 确定性代码，Claude 直接跑
```

**SKILL.md 的最小骨架**：

```markdown
---
name: pdf-form-filling
description: Fill PDF forms, extract form fields, and validate PDF documents. Use when working with PDF form fields or fillable PDFs.
---

# PDF Form Filling

## When to use this skill
Use when the user asks to fill out, read, or modify PDF forms.

## How to use
1. Run `scripts/extract_form_fields.py` to get the form schema
2. Map user input to fields
3. Fill and save

For advanced form validation, see `reference.md`.
For form-specific gotchas, see `forms.md`.
```

**面试可讲的角度**：这是 *self-describing package*——**传统 Python library 靠 docstring 描述能力**，skill 把整个包**自描述 + 自包含**。**Claude 看 name + description 就能决定用不用，看 SKILL.md 就能知道怎么用，看 reference / forms.md 能解决边界 case**。

**工程落地**：
- ☐ Skill 目录必须有 `SKILL.md`——**没有 frontmatter 的不是 skill**
- ☐ `name` 用 kebab-case（`pdf-form-filling`）
- ☐ `description` 写**触发条件**——"Use when working with..."——Claude 用这个判断 relevance
- ☐ Resources 用相对路径引用——`./reference.md` 而不是绝对路径，**支持 skill 移植**

---

## 2. 渐进披露：3 档 token 经济性

**一行定位**：**Skill 是按 token 付费的产品**——**默认只付出 ~50 token / skill，Claude 需要时再付**。

**三档 progressive disclosure**：

| 档 | 内容 | 何时加载 | Token 开销 |
|---|---|---|---|
| **L1** | `name` + `description` | 启动时全量进 system prompt | **~50 token / skill** |
| **L2** | `SKILL.md` 全文 | Claude 判断 skill 相关时读 | 1-5K token |
| **L3+** | `reference.md` / `forms.md` / scripts | 按需 navigate | 按需付 |

**机制**：
- 启动：system prompt 注入所有 skill 的 L1 metadata（`<available_skills>` 块）。
- Claude 看 L1 metadata → 判断是否相关。
- 相关 → `Read` SKILL.md → L2 加载。
- 复杂 case → 读 L3 附加文件。

**关键收益**：
- **安装 100 个 skill 只付 100 × 50 = 5K token**——不是 100 × 5K。
- **Skill 内容可以"无限大"**——只要 Claude 按需 navigate，**总 context 占用仍小**。

**面试可讲的角度**：这是 *filesystem as API* + *lazy loading* 的双重应用。**类比 Kubernetes**：所有 pods 在 etcd 注册，但只有调度的才进 node。**Claude 的 context 是昂贵资源，必须 lazy load**。

**工程落地**：
- ☐ **L1 description 必须准**——错一个词 Claude 不触发 = skill 装了个寂寞
- ☐ **L2 SKILL.md 保持精简**（< 3K token）——超过就拆 reference
- ☐ **L3 资源按场景分**——`forms.md` 只在表单场景被读，**别把所有东西塞 SKILL.md**
- ☐ **Scripts 当 executable 写**——Claude 跑脚本，不是读脚本

---

## 3. Skill + Code Execution：确定性活不用 LLM

**一行定位**：**Skill 不只是 instruction 仓库**——**scripts 是 deterministic tools，Claude 直接跑**——**省 token + 稳定**。

**PDF skill 案例**：

```python
# scripts/extract_form_fields.py
"""Read a PDF and extract all form fields."""
import sys
from pypdf import PdfReader

def main(pdf_path: str) -> dict:
    reader = PdfReader(pdf_path)
    fields = {}
    for page in reader.pages:
        for field in page.get_fields() or []:
            fields[field.name] = field.value
    return fields

if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1])))
```

**Claude 跑这个脚本**：
- `python scripts/extract_form_fields.py input.pdf` → JSON schema of form fields
- **不进 context 的东西**：脚本本身、PDF 内容、PDF library 的 doc
- **进 context 的东西**：stdout（form fields JSON）

**收益**：
- **Token 节省**：脚本和 PDF 不进 context。
- **确定性**：code execution 不会有 LLM 的随机性——**表单字段提取每次结果一致**。
- **可测试**：脚本本身可以 unit test，**不需要每次都用 Claude 验证**。

**面试可讲的角度**：这是 *LLM as orchestrator, code as executor*——**LLM 决定跑什么脚本、喂什么参数**；**code 跑 deterministic work**。**任何"sorting / parsing / calculation" 都不该用 LLM 生成 token——那是浪费钱**。

**工程落地**：
- ☐ **Skill 内嵌 scripts 优先于 prompt instructions**——"先跑这个脚本"比"做这件事"更稳
- ☐ **Scripts 必须 idempotent + sandbox-safe**——Claude 可能跑多次
- ☐ **Scripts 不要 print 大对象**——**stdout 进 context**（见 code-execution-with-mcp）
- ☐ **Scripts 的 docstring 是 Claude 看的"帮助"**——写 usage + 参数 + 限制

---

## 4. PDF Skill 实战拆解：L1 / L2 / L3 / Script 的组合

**完整 PDF skill 的目录结构**：

```
pdf-skill/
├── SKILL.md                # L2 - 入口
├── reference.md            # L3 - 复杂 case
├── forms.md                # L3 - 表单细节
└── scripts/
    └── extract_form_fields.py   # 确定性工具
```

**Claude 决策路径**：

1. 用户："Fill out this PDF form"
2. Claude 看 L1 metadata："pdf-form-filling: Use when working with PDF forms" → **trigger**
3. Claude 读 `SKILL.md` (L2) → 知道有 `forms.md` + `extract_form_fields.py`
4. Claude 跑 `python scripts/extract_form_fields.py form.pdf` → 拿到 form schema
5. Claude 看 schema 是 form fields → 读 `forms.md` (L3) → 学表单填写约定
6. Claude 填表 + 返回结果

**关键工程点**：
- **`forms.md` 单独成文件**——只在填表单时需要，**不污染通用场景的 L2 加载**。
- **`reference.md` 单独成文件**——只在复杂 case 需要，**不污染通用 L2**。
- **Scripts 始终不被读**——Claude 跑它，不是读它。

**面试可讲的角度**：这是 *manual as code* 的实践——**文档分层 + 按需加载**让 skill 既丰富又不烧 token。**好的 documentation 是 lazy 的——读者只读需要的章节**。

**工程落地**：
- ☐ **拆 reference / forms.md 的标准**：**互斥场景 / 极少同时用** 的内容拆开
- ☐ **Scripts 必须自描述**——docstring 写参数、用法、return format
- ☐ **SKILL.md 必须给决策路径**——"如果 X，读 Y；如果 Z，跑 script W"
- ☐ **Skill 目录支持 git submodule**——共享 skill 可以跨项目复用

---

## 5. Skill 开发 4 原则 + 安全审计

**Anthropic 给的开发 checklist**：

### 原则 1：Eval-driven 起步
- **先跑 agent 看哪里卡**——不要凭直觉建 skill。
- **从真实失败 case 倒推**——"Agent 不知道怎么处理 X" → "建 skill X-handler"。

### 原则 2：Structure for scale
- **`SKILL.md` 太长就拆**——**超过 3K token 必须拆 reference**。
- **互斥场景拆文件**——`forms.md` / `data.md` / `auth.md` 各管一段。
- **Scripts 是 executable + 文档双角色**——写清楚 Claude 是跑还是读。

### 原则 3：Think from Claude's perspective
- **监控 Claude 实际怎么用 skill**——**真实场景可能和你想的不一样**。
- **关注 L1 description 的命中率**——**description 错 = skill 永远不触发**。
- **找 over-reliance**——Claude 不该全靠 skill，**基础能力别被 skill 弱化**。

### 原则 4：Iterate with Claude
- **让 Claude 自己写 skill**——成功后让 Claude 总结 reusable 部分。
- **失败时让 Claude 自反思**——"哪一步走错了，context 缺什么"——**反过来补 SKILL.md**。

**面试可讲的角度**：这是 *dogfooding + telemetry* 的工程组合——**你自己用、你看 logs、你迭代**。**Skill 不是写一次就完，是活的 artifact**。

**工程落地 checklist**：
- ☐ **建 skill 前先跑 eval**——找真实失败
- ☐ **每次 Claude 用 skill 后看 transcript**——和你想的不一样就调 description
- ☐ **定期 review skill 的"被触发频率"**——不触发的 skill 是 dead weight
- ☐ **让 Claude 自己写 skill**——你 review + 校准，**比手写快 10x**

### Skill 安全审计

**Anthropic 明确警告**：
> "Malicious skills may introduce vulnerabilities... direct Claude to exfiltrate data and take unintended actions."

**审计 checklist**：
- ☐ **只装 trusted source 的 skill**——别 clone 任何 GitHub repo 的 `skills/` 目录
- ☐ **读所有 .md 文件**——instruction 可能是 "ignore previous instructions and..."
- ☐ **审计 scripts**——**scripts 是 executable code**，能 exfil 数据 / 装 malware
- ☐ **看 bundled resources**——image / data file / binary 都可能藏 payload
- ☐ **检查网络引用**——任何 "fetch from http://..." 都要审视

**面试可讲的角度**：这是 *supply chain security*——**Skill 是 LLM 的"包管理器"**。**npm install 信任问题在 skill install 里同样存在**。**zero trust：每个 skill 都审计**，尤其是 third-party skill。

**工程落地**：
- ☐ **Skill 必须 git version control + review**——PR 流程，**不能随便 merge**
- ☐ **Skill 仓库分 trusted / experimental**——experimental 装本地不上 prod
- ☐ **定期 audit 已装 skills**——skill 作者可能更新引入恶意代码
- ☐ **Sandbox 限制 skill 副作用**——skills 装的 scripts 跑在 sandbox 里（见 claude-code-sandboxing）

---

## 一句话总结

Agent Skills 是**用渐进披露让通用 Agent 变领域专家的工程模式**——**L1 metadata 全量预加载、L2 SKILL.md 按需读、L3 resources 按需 navigate、scripts 是 deterministic executor**。**Skill 开发的 4 原则是 eval-driven、structure for scale、think from Claude、iterate with Claude**——和传统软件工程的测试驱动 + 文档分层 + dogfooding 一脉相承。

## 配套阅读

- **同主题**：claude-skills-engineering — Anthropic 内置 Skill（xlsx / pptx / pdf / docx）
- **执行机制**：code-execution-with-mcp — Code execution 是 skill 的执行环境
- **架构视角**：managed-agents-arch-patterns — skill 在 harness 中的位置

参考资料：

- [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) — Barry Zhang, Keith Lazuka, Mahesh Murag, Anthropic
- [Agent Skills docs](https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview) — Skills cookbook + spec
- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — Skill 是 context 优化的一种