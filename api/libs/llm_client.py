import requests
from typing import List, Dict, Any


class LLMClient:
    def __init__(self, url: str, app_key: str, **kwargs):
        self.base_url = url
        self.app_key = app_key
        self.default_params = {
            "model": kwargs.get("model", ""),
            "temperature": kwargs.get("temperature", 0.7),
            "top_p": kwargs.get("top_p", 0.7),
            "presence_penalty": kwargs.get("presence_penalty", 0.0),
        }

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = None,
        temperature: float = None,
        top_p: float = None,
        presence_penalty: float = None,
        stream: bool = False,
        timeout: int = 60*5,
    ) -> Dict[str, Any]:
        """
        发起一次语义模型对话请求。
        """
        payload = {
            "messages": messages,
            "model": model or self.default_params["model"],
            "stream": stream,
            "temperature": temperature or self.default_params["temperature"],
            "top_p": top_p or self.default_params["top_p"],
            "presence_penalty": presence_penalty or self.default_params["presence_penalty"],
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": self.app_key,
        }

        try:
            response = requests.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=(5, 10*60),
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            return {"error": str(e)}
