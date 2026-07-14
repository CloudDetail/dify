from pathlib import Path
from typing import Any
import copy

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "init_data" / "workflows" / "zh"
SOURCE = WORKFLOW_DIR / "告警简单根因分析.yml"
TARGET = WORKFLOW_DIR / "告警简单根因分析V2.yml"
ENVIRONMENT_NODE_ID = "v2_runtime_environment_context"

ENVIRONMENT_CODE = '''def main(pod: str, container_id: str, node: str, pid: str) -> dict:
    pod = str(pod or "").strip()
    container_id = str(container_id or "").strip()
    node = str(node or "").strip()
    pid = str(pid or "").strip()

    if not pod and not container_id and node and pid:
        return {
            "scene": "vm",
            "instance_term": "进程实例",
            "location_text": f"主机 {node} 上的进程 PID {pid}",
            "allowed_command_context": "top, pidstat, ss, nstat, iotop, strace, perf, systemctl, journalctl",
            "forbidden_terms": "Pod, 容器, Namespace, Deployment, K8s, Kubernetes, OOMKill, kubectl, docker",
            "prompt_context": "当前为纯虚拟机环境。使用主机、进程、PID、系统服务等术语；禁止输出任何容器或 Kubernetes 专属术语与命令。",
        }
    if pod or container_id:
        return {
            "scene": "container",
            "instance_term": "应用实例",
            "location_text": pod or container_id,
            "allowed_command_context": "仅使用与现有证据匹配的容器或 Kubernetes 命令",
            "forbidden_terms": "",
            "prompt_context": "当前为容器环境，可使用 Pod、容器和 Kubernetes 术语，但命令必须与证据匹配。",
        }
    return {
        "scene": "unknown",
        "instance_term": "实例",
        "location_text": node,
        "allowed_command_context": "使用跨环境通用诊断命令",
        "forbidden_terms": "不得猜测 Pod、容器或虚拟机",
        "prompt_context": "当前运行环境不明确，必须使用实例、运行节点、进程或服务等中性术语。",
    }
'''

ENV_AWARE_TITLES = {
    "llm analysis root cause",
    "网络方向分析",
    "总结下游影响",
    "可行动方向建议",
    "可行动建议JSON",
    "根因方向JSON",
    "生成报告展示结构",
}


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def node_by_id(document: dict, node_id: str) -> dict:
    for node in document["workflow"]["graph"]["nodes"]:
        if node["id"] == node_id:
            return node
    raise KeyError(node_id)


def add_environment_context(document: dict) -> None:
    graph = document["workflow"]["graph"]
    graph["nodes"].append(
        {
            "id": ENVIRONMENT_NODE_ID,
            "type": "custom",
            "position": {"x": 4118, "y": 420},
            "positionAbsolute": {"x": 4118, "y": 420},
            "width": 244,
            "height": 54,
            "selected": False,
            "sourcePosition": "right",
            "targetPosition": "left",
            "data": {
                "type": "code",
                "title": "运行环境上下文",
                "desc": "",
                "code_language": "python3",
                "code": ENVIRONMENT_CODE,
                "selected": False,
                "variables": [
                    {"variable": "pod", "value_selector": ["1742807803325", "pod"]},
                    {"variable": "container_id", "value_selector": ["1742807803325", "containerId"]},
                    {"variable": "node", "value_selector": ["1742807803325", "node"]},
                    {"variable": "pid", "value_selector": ["1742807803325", "pid"]},
                ],
                "outputs": {
                    "scene": {"type": "string", "children": None},
                    "instance_term": {"type": "string", "children": None},
                    "location_text": {"type": "string", "children": None},
                    "allowed_command_context": {"type": "string", "children": None},
                    "forbidden_terms": {"type": "string", "children": None},
                    "prompt_context": {"type": "string", "children": None},
                },
            },
        }
    )
    graph["edges"].append(
        {
            "id": f"1742807803325-source-{ENVIRONMENT_NODE_ID}-target",
            "type": "custom",
            "source": "1742807803325",
            "sourceHandle": "source",
            "target": ENVIRONMENT_NODE_ID,
            "targetHandle": "target",
            "selected": False,
            "zIndex": 0,
            "data": {
                "isInIteration": False,
                "sourceType": "code",
                "targetType": "code",
            },
        }
    )


def inject_environment_prompts(document: dict) -> None:
    section = (
        "\n\n# 运行环境约束\n"
        "{{#v2_runtime_environment_context.prompt_context#}}\n"
        "运行环境上下文优先于知识库或通用示例；若知识库命令与当前环境冲突，必须忽略冲突命令。"
    )
    for node in document["workflow"]["graph"]["nodes"]:
        data = node.get("data", {})
        if data.get("title") not in ENV_AWARE_TITLES:
            continue
        for prompt in data.get("prompt_template", []):
            if prompt.get("role") == "user":
                prompt["text"] = prompt.get("text", "") + section


def build() -> dict:
    document = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    document = copy.deepcopy(document)
    document["app"]["name"] = "告警简单根因分析V2"
    add_environment_context(document)
    inject_environment_prompts(document)
    return document


def main() -> None:
    document = build()
    TARGET.write_text(
        yaml.dump(
            document,
            Dumper=NoAliasDumper,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
