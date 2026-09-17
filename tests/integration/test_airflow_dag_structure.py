import ast
import os
from pathlib import Path
import subprocess

import pytest


DAG_PATH = Path(__file__).parents[2] / "airflow" / "dags" / "daily_iaas_inspection.py"
EXPECTED_TASKS = [
    "generate_dataset",
    "create_run",
    "execute_inspections",
    "correlate_risks",
    "reverify_pending_risks",
    "build_resource_summaries",
    "build_snapshot",
    "complete_run",
]


def test_airflow_dag_uses_http_boundary_and_has_no_django_or_app_imports():
    source = DAG_PATH.read_text()
    tree = ast.parse(source)
    imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ] + [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ]

    assert "requests" in imports
    assert not any(name == "django" or name.startswith("django.") for name in imports)
    assert not any(name == "apps" or name.startswith("apps.") for name in imports)
    assert not any(name == "services" or name.startswith("services.") for name in imports)


def test_dag_declares_exact_literal_stage_edges():
    source = DAG_PATH.read_text()
    tree = ast.parse(source)
    task_ids = {
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "task_id"
        and isinstance(keyword.value, ast.Constant)
    }
    # The source-level check remains useful in the web test environment where
    # Airflow is intentionally installed in a separate virtualenv.
    assert set(EXPECTED_TASKS).issubset(task_ids)
    assert "generate_dataset >> create_run >> execute_inspections" in source
    assert "execute_inspections >> correlate_risks >> reverify_pending_risks" in source
    assert "reverify_pending_risks >> build_resource_summaries" in source
    assert "build_resource_summaries >> build_snapshot >> complete_run" in source


def test_dag_requires_a_valid_environment_id_before_making_http_requests():
    source = DAG_PATH.read_text()
    assert "INSPECTION_ENVIRONMENT_ID" in source
    assert "must be configured as a valid UUID" in source
    assert "environment_id = _configured_environment_id()" in source


def test_nonproducing_stage_callables_do_not_return_http_responses_or_risk_ids():
    tree = ast.parse(DAG_PATH.read_text())
    nonproducing = {
        "execute_inspections_task",
        "correlate_risks_task",
        "reverify_pending_risks_task",
        "build_resource_summaries_task",
        "build_snapshot_task",
        "complete_run_task",
    }
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    for name in nonproducing:
        returns = [node.value for node in ast.walk(functions[name]) if isinstance(node, ast.Return)]
        assert any(isinstance(value, ast.Constant) and value.value is None for value in returns)
        assert not any(
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "_post"
            for value in returns
        )


def test_dag_import_without_environment_id_fails_with_explicit_configuration_error():
    airflow_python = Path("/Users/lars.li/Documents/AI-inspect/.venv-airflow/bin/python")
    if not airflow_python.exists():
        pytest.skip("Airflow 2.3.2 virtualenv is not installed")
    environment = os.environ.copy()
    environment.pop("INSPECTION_ENVIRONMENT_ID", None)
    environment["AIRFLOW_HOME"] = str(DAG_PATH.parents[2] / ".airflow-task9-F9DM8z")
    environment["AIRFLOW__CORE__LOAD_EXAMPLES"] = "False"
    result = subprocess.run(
        [
            str(airflow_python),
            "-c",
            (
                "import runpy; runpy.run_path("
                f"{str(DAG_PATH)!r}"
                ")"
            ),
        ],
        cwd=DAG_PATH.parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "INSPECTION_ENVIRONMENT_ID must be configured as a valid UUID" in (
        result.stdout + result.stderr
    )
