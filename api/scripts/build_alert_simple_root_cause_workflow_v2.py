from pathlib import Path
from typing import Any
import copy

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / "init_data" / "workflows" / "zh"
SOURCE = WORKFLOW_DIR / "告警简单根因分析.yml"
TARGET = WORKFLOW_DIR / "告警简单根因分析V2.yml"


class NoAliasDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def node_by_id(document: dict, node_id: str) -> dict:
    for node in document["workflow"]["graph"]["nodes"]:
        if node["id"] == node_id:
            return node
    raise KeyError(node_id)


def build() -> dict:
    document = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
    document = copy.deepcopy(document)
    document["app"]["name"] = "告警简单根因分析V2"
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
