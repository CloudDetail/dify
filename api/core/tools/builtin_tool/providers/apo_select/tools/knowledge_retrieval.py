import json
from collections.abc import Generator
from typing import Any, Optional

import requests

from configs import dify_config
from core.tools.builtin_tool.tool import BuiltinTool
from core.tools.entities.tool_entities import ToolInvokeMessage


class KnowledgeRetrievalTool(BuiltinTool):
    def _invoke(
        self,
        user_id: str,
        tool_parameters: dict[str, Any],
        conversation_id: Optional[str] = None,
        app_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> Generator[ToolInvokeMessage, None, None]:
        # 获取参数
        query = tool_parameters.get('query')
        knowledge_base_id = tool_parameters.get('knowledge_base_id')
        top_k = tool_parameters.get('top_k', 5)
        score_threshold = tool_parameters.get('score_threshold', 0.0)

        data = {
            "query": query,
            "knowledge_id": knowledge_base_id or dify_config.APO_DEFAULT_KNOWLEDGE_BASE_ID,
            "retrieval_setting": {
                "top_k": top_k,
                "score_threshold": score_threshold
            }
        }

        try:
            url = dify_config.APO_KNOWLEDGE_BASE_URL + '/retrieval'
            response = requests.post(
                url, json=data, timeout=30)

            if response.status_code == 200:
                result = response.json()
                yield self.create_text_message(json.dumps(result, ensure_ascii=False))
            else:
                yield self.create_text_message(json.dumps({
                    'success': False,
                    'error': f'检索服务返回错误: {response.status_code}',
                    'details': response.text
                }))
        except Exception as e:
            yield self.create_text_message(json.dumps({
                'success': False,
                'error': f'请求检索服务时发生错误: {str(e)}'
            }))
