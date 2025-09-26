from collections.abc import Generator
from typing import Any, Optional

from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


class ClassifyAnalysisTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        detect_name = tool_parameters.get("algorithmName")
        data = tool_parameters.get("data")
        history = tool_parameters.get("history")
        res = ""
        match detect_name:
            case "classify_detect":
                pass
        yield self.create_text_message(res)
