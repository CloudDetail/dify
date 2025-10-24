import json
from collections.abc import Generator
from typing import Any, Optional


from configs import dify_config
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage
from libs.llm_client import LLMClient
from libs.json_in_md_parser import parse_and_check_json_markdown

from core.workflow.nodes.question_classifier.template_prompts import (
    QUESTION_CLASSIFIER_ASSISTANT_PROMPT_1,
    QUESTION_CLASSIFIER_ASSISTANT_PROMPT_2,
    QUESTION_CLASSIFIER_SYSTEM_PROMPT,
    QUESTION_CLASSIFIER_USER_PROMPT_1,
    QUESTION_CLASSIFIER_USER_PROMPT_2,
    QUESTION_CLASSIFIER_USER_PROMPT_3,
)


class LLMClassifierTool(BuiltinTool):
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
        input_text = tool_parameters.get("input", "")
        instruction = tool_parameters.get("instruction", "")
        categories_string = tool_parameters.get("categories", "")
        categories_arr = json.loads(categories_string)
        categories = []
        for i, category in enumerate[Any](categories_arr):
            categories.append({
                "category_id": i,
                "category_name": category
            })

        messages = [
            {"role": "system", "content": QUESTION_CLASSIFIER_SYSTEM_PROMPT.format(
                histories="")},
            {"role": "user", "content": QUESTION_CLASSIFIER_USER_PROMPT_1},
            {"role": "assistant", "content": QUESTION_CLASSIFIER_ASSISTANT_PROMPT_1},
            {"role": "user", "content": QUESTION_CLASSIFIER_USER_PROMPT_2},
            {"role": "assistant", "content": QUESTION_CLASSIFIER_ASSISTANT_PROMPT_2},
            {"role": "user", "content": QUESTION_CLASSIFIER_USER_PROMPT_3.format(
                input_text=input_text,
                categories=json.dumps(categories, ensure_ascii=False),
                classification_instructions=instruction,
            )}
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

            result_text = response.get("choices", [{}])[0].get(
                "message", {}).get("content", "")
            if not result_text:
                yield self.create_text_message("Error: Empty response from model")
                return

            try:
                result_json = parse_and_check_json_markdown(
                    result_text, ["category_name", "category_id"])
                category_name = result_json.get("category_name", "")

                yield self.create_text_message(category_name)
            except Exception as e:

                yield self.create_text_message(result_text)
                return
        except Exception as e:
            yield self.create_text_message(f"Error: {e}")
            return
