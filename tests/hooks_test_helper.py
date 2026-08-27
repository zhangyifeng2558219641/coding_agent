"""供 test_extensions.py 的可调用钩子测试使用。"""

records = []


def record(event=None, **ctx):
    records.append({"event": event, "tool_name": ctx.get("tool_name"),
                    "success": ctx.get("tool_success")})
    return True
