import ast
from pathlib import Path


DAG_PATH = Path(__file__).parents[2] / "airflow" / "dags" / "daily_iaas_inspection.py"
EXPECTED_TASKS = [
    "generate_dataset",
    "create_run",
    "execute_inspections",
    "correlate_risks",
    "reverify_pending_risks",
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
    assert "reverify_pending_risks >> build_snapshot >> complete_run" in source
