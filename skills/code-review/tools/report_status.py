"""code-review 技能附带的一个小工具:生成审查进度状态。"""

from codingagent.tools import Tool, ToolContext
from codingagent.types import ToolResult


class ReviewStatus(Tool):
    name = "ReviewStatus"
    description = "返回当前代码审查的检查清单状态,帮助不遗漏审查维度。"
    parameters = {"type": "object", "properties": {}}
    category = "skill"

    def run(self, ctx: ToolContext, **kwargs):
        checklist = (
            "审查清单:\n"
            "- [ ] 正确性:逻辑/边界/异常\n"
            "- [ ] 安全性:注入/敏感信息/权限\n"
            "- [ ] 可维护性:命名/重复/复杂度\n"
            "- [ ] 性能:重复计算/无效I/O"
        )
        return ToolResult(name=self.name, success=True, output=checklist)


TOOLS = [ReviewStatus()]
