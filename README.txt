一、Git 仓库地址
https://github.com/zhangyifeng2558219641/coding_agent

二、视频演示的agent生成项目
路径:./demo
会话json文件：./demo/商城项目功能实现.json

三、如何运行
1. conda create -n coding_agent python=3.13 -y && conda activate coding_agent
2. pip install -r requirements.txt && pip install -e .
3. cp .env.example .env,填入 DEEPSEEK_API_KEY(.env 已 gitignore,不入库)
4. 交互终端:python -m codingagent
   一次性任务:python -m codingagent run "任务"
   网页端:python -m codingagent web(打开 http://127.0.0.1:8787)
   自检:python -m codingagent doctor;其它目录加 -w D:\项目

四、特色功能
1. 不用任何 agent 框架:SSE 客户端、上下文压缩、工具定义与本地执行、模型输出解析、循环终止、错误处理全部自行实现,亦不依赖服务端托管执行。
2. 双端交互:rich 终端(流式+多行+斜杠命令)与网页端(会话管理+SSE 流式+Markdown 渲染+代码高亮)共用同一核心。
3. 10 个内置工具:ReadFile/WriteFile/EditFile(严格差异)/Bash/Glob/Grep/WebSearch/MemoryRecall/MemorySave/DispatchTask,外加任意 MCP 工具。
4. 5 层纵深权限:工具名单、敏感路径拦截、工作区沙箱、危险命令确认、交互/自动/拒绝模式。
5. 扩展:Skill 技能包、18 条斜杠命令、钩子、跨会话记忆、SubAgent、MCP、Worktree、Agent Teams。
6. Web 特色:计划模式(只读计划→批准执行)、检查点/回滚(改文件自动快照一键还原)、会话导出/导入、主题切换、停止生成与重发、ask_user 选项、会话重命名与搜索、代码块复制。

五、其它
- 默认 DeepSeek(OpenAI 兼容),base_url/模型/key 全可配。
- 148 个 pytest 用例全部 mock LLM、免真实 key。
- 详细设计见设计方案.md,使用见项目使用方式说明.md。
