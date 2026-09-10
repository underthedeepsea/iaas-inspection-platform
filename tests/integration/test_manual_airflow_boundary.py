import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest


PATH = Path('airflow/dags/iaas_manual_inspection.py')


def load_callable():
    tree = ast.parse(PATH.read_text())
    # Execute only imports/constants/callable, without importing Airflow or Django.
    body = [node for node in tree.body if not isinstance(node, ast.With) and not (isinstance(node, ast.ImportFrom) and (node.module or '').startswith('airflow'))]
    scope = {}
    exec(compile(ast.Module(body=body, type_ignores=[]), str(PATH), 'exec'), scope)
    return scope


def test_manual_dag_calls_existing_internal_stages_and_retries_http_failures(monkeypatch):
    scope = load_callable()
    post = Mock()
    monkeypatch.setattr(scope['requests'], 'post', post)
    run_id = str(uuid.uuid4())
    scope['run_manual_inspection'](dag_run=SimpleNamespace(conf={'run_id':run_id}))
    assert [call.args[0].split('/')[-2] for call in post.call_args_list] == list(scope['STAGES'])
    assert all(call.kwargs['json'] == {} for call in post.call_args_list)
    post.reset_mock()
    post.return_value.raise_for_status.side_effect = RuntimeError('HTTP failure')
    with pytest.raises(RuntimeError):
        scope['run_manual_inspection'](dag_run=SimpleNamespace(conf={'run_id':run_id}))
    assert post.call_count == 1
    assert "'retries': 2" in PATH.read_text()


def test_production_dags_never_import_django_business_or_ai():
    for path in Path('airflow/dags').glob('*.py'):
        tree = ast.parse(path.read_text())
        names = [node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)] + [alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names]
        assert not any(name and name.split('.')[0] in {'django','apps','services','langgraph'} for name in names)
    assert not Path('airflow/dags/iaas_resource_investigation.py').exists()
