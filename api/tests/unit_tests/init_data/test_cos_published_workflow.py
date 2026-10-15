"""发布图一致性校验：历史或draft命中不能替代当前published版本。"""

import ast
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Union

import pytest
import yaml


@pytest.mark.parametrize("matches", [False, True])
def test_only_current_published_workflow_controls_update(matches):
    source = Path(__file__).parents[3] / "initializer/workflow.py"
    fn = next(
        n
        for n in ast.parse(source.read_text()).body
        if isinstance(n, ast.FunctionDef) and n.name == "_check_workflow_to_update"
    )
    app = SimpleNamespace(id="app", workflow_id="published")
    target = {"nodes": [{"id": "new"}], "edges": []}
    published = SimpleNamespace(graph=json.dumps(target if matches else {"nodes": []}), features="{}")

    class Field:
        def __eq__(self, other):
            return other

    App = SimpleNamespace(name=Field(), tenant_id=Field(), mode=Field(), status=Field())
    Workflow = SimpleNamespace(id=Field(), app_id=Field())

    class Query:
        def __init__(self, model):
            self.model = model

        def filter(self, *conditions):
            if self.model is Workflow:
                assert conditions == ("published", "app")
            return self

        def first(self):
            return app if self.model is App else published

    session = SimpleNamespace(query=lambda model: Query(model))
    ns = {"Union": Union, "yaml": yaml, "json": json, "logging": logging, "App": App, "Workflow": Workflow}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), "exec"), ns)
    result = ns["_check_workflow_to_update"](
        session,
        yaml.safe_dump({"app": {"name": "test"}, "workflow": {"graph": target, "features": {}}}),
        SimpleNamespace(current_tenant_id="tenant"),
    )
    assert result == (False if matches else "app")
