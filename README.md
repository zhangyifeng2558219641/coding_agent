# Coding Agent · 自研编程智能体

一个类 Claude Code 的编程智能体:通过与 LLM 对话,自主地读写文件、执行命令、搜索代码,完成交给它的编程任务。**不使用任何 agent 框架 / SDK**(LangChain、OpenAI Agents SDK、Claude Agent SDK、AutoGen 等一律不用),对话历史与上下文管理、工具定义与本地执行、模型输出解析、循环终止条件、错误处理等核心逻辑**全部自行实现**。

- **技术栈**:Python 3.13 · `requests`(手写 SSE + tool calling)· `rich`(终端)· FastAPI + uvicorn(网页端)
- **默认模型**:DeepSeek(`https://api.deepseek.com`,OpenAI 兼容网关,`base_url`/模型/API key 全可配置)
- **双端交互**:rich 终端与网页端共用同一套 Agent 核心,仅 UI 层不同

---

## 功能特性

### 核心能力
- **ReAct 主循环**:想 → 调工具 → 看结果 → 再决策;终止条件自洽(无工具调用 / 达到最大迭代 / 用户中断 / 上下文预算耗尽)
- **OpenAI 兼容客户端**:`requests` 直连 + **手写 SSE 流式解析** + **原生 tool calling 增量累积**,不依赖任何模型 SDK
- **对话历史与上下文管理**:可插拔 system 段(基础提示 / 跨会话记忆 / 已装载技能 / 压缩摘要)、超长工具输出自动截断、**超预算自动压缩为摘要**(压缩失败时回滚、宁可多用 token 也不丢上下文)
- **工具系统**:统一 `Tool` 接口 + JSON-schema 参数定义与校验,**全部在本机进程内本地执行**
- **错误处理**:SSE 容错、非 2xx 指数退避重试、鉴权失败明确报错、单工具异常只记为一条结果不中断任务

### 工具(10 个内置 + 任意 MCP 远端)
`ReadFile` / `WriteFile` / `EditFile`(严格旧文本匹配的差异编辑)/ `Bash`(超时强杀进程树)/ `Glob` / `Grep`(纯 Python 实现)/ `WebSearch`(无 key 抓取 Bing)/ `MemoryRecall` / `MemorySave`(跨会话记忆)/ `DispatchTask`(并行子任务),以及经 MCP 协议挂载的外部工具。

### 5 层纵深权限防御
工具名单 → 敏感路径拦截(`.env`、`.git`、密钥文件)→ 工作区沙箱 → 危险命令确认(`rm -rf`、`git push --force` 等)→ 交互 / 自动放行 / 拒绝 三种模式。**Agent 有能力但不失控。**

### 扩展系统
**MCP** 协议(自写 stdio + JSON-RPC 2.0 客户端)、**Skill** 技能包、**斜杠命令**(18 条内置 + 自定义)、**生命周期钩子**(可 veto 工具调用)、**跨会话记忆**、**SubAgent** 并行、**Git Worktree** 隔离、**Agent Teams**(多角色成员并行,负责人汇总;内置 review / tsp / scrum 团队)。

### Web 端增强(单文件前端,无构建)
- 会话管理:按最近活动置顶、搜索过滤、双击重命名、**导出(Markdown / JSON / 纯文本)/ 导入**
- **SSE 流式**渲染模型输出与工具调用过程;**自写 Markdown 渲染器 + 代码高亮**(零外部依赖,所有文本先转义,杜绝 XSS)
- **计划模式**(Plan Mode):只读调研出结构化计划,「批准并执行」后才动手
- **检查点 / 回滚**:每次写/改文件自动快照 before/after,右侧面板看 diff、一键还原工作区
- 交互式权限审批按钮、`ask_user` 选项选择、斜杠命令自动补全、停止生成、6 套主题即时切换

### 安全
所有 API key 一律通过环境变量或 `.env` 提供,**仓库内无任何真实密钥**;`.env` 已 gitignore;配置接口与 `doctor` 只回显"是否已配置",不泄露 key。

---

## 快速开始

```bash
conda create -n coding_agent python=3.13 -y
conda activate coding_agent
pip install -r requirements.txt
pip install -e .              # 可编辑安装:之后可在任意目录启动,用 -w 指定工作区
cp .env.example .env          # 填入 DEEPSEEK_API_KEY(Windows:copy .env.example .env)
```

运行(四种子命令):

```bash
python -m codingagent            # 交互式终端(类 Claude Code,流式+多行+斜杠命令)
python -m codingagent run "读取 README.md 并补一行说明"   # 一次性任务(适合录演示视频)
python -m codingagent web        # 网页端 http://127.0.0.1:8787
python -m codingagent doctor     # 环境自检(工作区/模型/工具/技能/权限/MCP 状态)
```

处理其它目录的项目:`pip install -e .` 之后 `cd` 进目标项目直接启动(自动按最近 `.git` 找工作区),或用 `-w` 显式指定:

```bash
python -m codingagent -w D:\另一个项目 web
```

> 换目录后 API key 需放在用户级 `~/.coding_agent/.env` 或系统环境变量(优先级:进程环境变量 > `<工作区>/.env` > `~/.coding_agent/.env`)。

---

## 架构

```
                 ┌────────────────────────────┐
                 │    UI 层(可插拔,同一 UISink) │
                 │  CLI(rich)  /  Web(FastAPI+SSE)
                 └──────────────┬─────────────┘
                                │ 事件(event / ask)
                 ┌──────────────▼─────────────┐
                 │   agent/loop.py   ReAct 循环 │
                 │  想 → 调工具 → 看结果 → 再决策  │
                 └───┬──────┬──────┬──────┬─────┘
        ┌────────────┘      │      │      └────────────┐
        ▼                   ▼      ▼                    ▼
┌──────────────┐  ┌───────────────┐  ┌──────────────┐  ┌──────────────┐
│  tools/ 工具集 │  │ agent/permissions│ │ llm/history   │  │ 扩展系统        │
│ 10内置+记忆+   │  │ 5 层纵深权限     │ │ 上下文管理与压缩 │  │ MCP/技能/钩子/  │
│ 子任务+MCP 工具 │  └───────────────┘  └──────────────┘  │ 斜杠命令/团队/   │
└──────────────┘                                          │ worktree/记忆   │
        │                                                └──────────────┘
        ▼
┌──────────────┐
│ llm/client.py │  自写 OpenAI 兼容客户端(requests + SSE + tool calling)
└──────────────┘
```

**数据流**:用户输入 → `History`(维护消息与 system 提示)→ `ChatClient` 流式请求 → 文本实时渲染 + 原生 tool calling → 逐条过 `PermissionPolicy` 裁决 → 本地执行工具 → 结果截断后写回 `History` → 继续循环,直至任一终止条件。`UISink` 是 CLI / Web 共用的事件接口,同一事件源、两种渲染。

---

## 权限模式

| mode | 行为 |
|---|---|
| `interactive`(默认) | 未知操作逐次询问(CLI 输入 y/n;Web 端输入框上方弹「允许/拒绝」按钮) |
| `auto-approve` | 白名单外自动放行(需用户明确开启) |
| `deny` | 白名单外一律拒绝 |

纵深防御:敏感路径直接拒绝、越沙箱需确认、危险命令需确认。可在 `config.yaml` 配置 `allow_tools` / `deny_tools` / `ask_tools` / `allow_commands` / `dangerous_commands` / `sensitive_paths` / `sensitive_file_names`。

---

## 斜杠命令(18 条)

| 命令 | 说明 |
|---|---|
| `/help` `/status` `/exit` | 帮助 / 会话状态 / 退出 |
| `/clear` `/model <名>` `/tools` `/permissions` | 清空上下文 / 切换模型 / 列工具 / 权限策略 |
| `/memory [project\|user\|save…\|clear]` | 跨会话记忆 |
| `/skills [list\|load\|unload]` `/compact` `/cost` | 技能包 / 手动压缩 / 用量与费用 |
| `/mcp [list\|connect\|disconnect]` | MCP servers 管理 |
| `/team <团队名> <任务>` `/worktree [list\|create\|remove]` | Agent 团队 / Git worktree |
| `/plan [<任务>]` `/execute` | 计划模式(只读调研→计划→批准执行) |
| `/checkpoint [list\|rollback <n>]` | 文件检查点 / 一键回滚 |
| `/resume` | 恢复 CLI 历史会话 |

自定义命令:在 `.coding_agent/commands/` 放 `*.md`(首行 `# 名称 - 说明`,正文为 prompt 模板,`{args}` 替换为参数),示例见 `examples/commands/plan.md`。

---

## 配置(`config.yaml`)

| 段 | 关键项 | 说明 |
|---|---|---|
| `provider` | `base_url` / `model` / `temperature` / `max_tokens` | 模型厂商与参数,任意 OpenAI 兼容网关可换 |
| `context` | `budget_tokens` / `max_tool_output` | 上下文预算(超限自动压缩)、单条工具输出上限 |
| `agent` | `max_iterations` | 单任务最大工具迭代轮数 |
| `permissions` | `mode` / `sandbox` / 名单 | 权限策略 |
| `memory` | `enabled` / 文件路径 | 跨会话记忆 |
| `search` | `base_url` / `timeout` / `proxy` | WebSearch 参数(无需 key) |
| `mcp` | `servers` | 外部工具服务 |
| `teams` | 成员定义 | 多 Agent 团队 |
| `hooks` | 事件 → 命令/可调用 | 生命周期钩子 |

配置优先级:默认值 < `config.yaml` < 用户级/项目级覆盖 < `.env` < 进程环境变量 < 命令行参数。

---

## 测试

```bash
python -m pytest tests/ -q
```

148 个 pytest 用例,**全部使用 mock LLM,无需真实 API key**,覆盖配置 / token 估算 / 工具 / EditFile 严格匹配 / 权限决策矩阵 / ReAct 循环端到端 / 上下文压缩 / 斜杠命令 / 钩子 / MCP / 技能 / Web API(CRUD + SSE)/ 检查点回滚等核心逻辑。

---

## 文档

- [设计方案](设计方案.md) — 架构、核心设计、答辩要点
- [项目结构](项目结构.md) — 目录树、模块职责、数据流
- [项目使用方式说明](项目使用方式说明.md) — 环境 / 启动 / 配置 / 权限 / FAQ

---

## 与题目要求对齐

- **重要逻辑全部实现**:模型客户端与 SSE 解析、对话历史与上下文管理、工具定义与本地执行、模型输出解析、循环终止条件、错误处理,均未使用任何 agent 框架 / SDK;不依赖服务端托管的代码执行或文件工具(Code Interpreter / Files API 均未使用)。
- **API key 不落地**:只走环境变量 / `.env`(已 gitignore),仓库、本 README 与视频中均不含真实密钥。
- **完整提交历史**:项目提交保留完整开发过程。
