import json
from collections.abc import Generator
from typing import Any, Optional


from configs import dify_config
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.llm_client import LLMClient


class ModelCallTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        model = tool_parameters.get("model", "")
        temperature = tool_parameters.get("temperature", 0.7)
        top_p = tool_parameters.get("top_p", 0.7)
        presence_penalty = tool_parameters.get("presence_penalty", 0.0)
        user = tool_parameters.get("user", "")
        system = tool_parameters.get("system", "")
        messages = []

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            llm_client = LLMClient(
                app_key=dify_config.AI_PLATFORM_LLM_API_KEY,
                url=dify_config.AI_PLATFORM_LLM_URL,
                temperature=temperature,
                top_p=top_p,
                presence_penalty=presence_penalty,
            )
            response = llm_client.chat(
                model=model,
                messages=messages,
            )
            if "error" in response:
                yield self.create_text_message(f"Error: {response['error']}")
                return
        except Exception as e:
            yield self.create_text_message(f"Error: {e}")
            return
        yield self.create_text_message(response.choices[0].message.content)
