# coding_agent

自研编程智能体(类 Claude Code):与大语言模型对话,自主读写文件、执行命令完成编程任务。不使用任何 agent 框架,重要逻辑(对话历史与上下文管理、工具定义与本地执行、模型输出解析、循环终止条件、错误处理)全部自行实现。

## 快速开始

```bash
conda create -n coding_agent python=3.13 -y
conda activate coding_agent
pip install -r requirements.txt
pip install -e .            # 可编辑安装:之后可在任意目录启动,用 -w 指定工作区
cp .env.example .env    # 填入 DEEPSEEK_API_KEY(要在任意目录启动,key 放 ~/.coding_agent/.env)

python -m codingagent          # 交互式终端(类 Claude Code)
python -m codingagent run "任务"  # 一次性任务
python -m codingagent web      # 网页端 http://127.0.0.1:8787
python -m codingagent -w D:\另一个项目 web   # 处理其它目录的项目
python -m codingagent doctor   # 环境自检
```

## 特性

- **双端交互**:rich 终端(流式、多行、斜杠命令)+ FastAPI 网页端(对话管理、SSE 流式),共用同一套 Agent 核心
- **7 大核心工具**:ReadFile / WriteFile / EditFile(严格差异编辑)/ Bash / Glob / Grep / WebSearch(联网搜索)
- **5 层纵深权限**:危险命令确认、敏感路径拦截、工作区沙箱、白名单、审批模式
- **扩展系统**:MCP 协议、Skill 技能包、斜杠命令、生命周期钩子、跨会话记忆、SubAgent、Git Worktree、Agent Teams
- **上下文压缩 + Token 管理**:超预算自动摘要历史
- **模型可配**:默认 DeepSeek(OpenAI 兼容),base_url/模型/API key 全可配置,凭据仅走环境变量/.env

## 文档

- [设计方案](设计方案.md)
- [项目结构](项目结构.md)
- [项目使用方式说明](项目使用方式说明.md)

## 测试

```bash
python -m pytest tests/ -q   # 64 个用例,mock LLM,免真实 API key
```
