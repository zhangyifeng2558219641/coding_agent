编程智能体(coding agent)

一、Git 仓库地址
(提交时在此填写仓库地址,如 https://github.com/<用户名>/<仓库名>)

二、如何运行
1. conda create -n coding_agent python=3.13 -y
2. conda activate coding_agent
3. pip install -r requirements.txt
4. 复制 .env.example 为 .env,填入 DEEPSEEK_API_KEY
5. 交互终端:python -m codingagent
   一次性任务:python -m codingagent run "任务描述"
   网页端:python -m codingagent web(打开 http://127.0.0.1:8787)
   自检:python -m codingagent doctor

三、特色功能
1. 双端交互:rich 终端(流式+多行+斜杠命令)与 FastAPI 网页端(对话管理+SSE 流式)共用同一套 Agent 核心。
2. 自写重要逻辑:requests+手写 SSE 的 OpenAI 兼容客户端、tool calling 累积、对话历史与上下文压缩、ReAct 循环终止条件、错误处理,均未使用任何 agent 框架。
3. 6 大核心工具:ReadFile/WriteFile/EditFile(严格旧文本匹配)/Bash/Glob/Grep。
4. 5 层纵深权限:危险命令确认、敏感路径拦截、工作区沙箱、白名单、审批模式,Agent 有能力但不失控。
5. 扩展系统:MCP 协议接入(stdio+JSON-RPC 2.0)、Skill 技能包、斜杠命令、生命周期钩子、跨会话记忆、SubAgent 并行、Git Worktree 隔离、Agent Teams。
6. 上下文压缩与 Token 管理,超预算自动摘要历史。
7. 模型与 API key 全部可配置,凭据仅走环境变量/.env,不入库。

四、其它
- 默认模型 DeepSeek(OpenAI 兼容),base_url/模型可任意切换。
- 42 个单元测试(mock LLM,免真实 key):python -m pytest tests/ -q。
- 详细设计见设计方案.md,结构见项目结构.md,使用见项目使用方式说明.md。
