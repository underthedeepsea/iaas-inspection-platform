import re
from importlib.metadata import version
from pathlib import Path
import subprocess
import sys

import django


def test_project_version_uses_three_numeric_parts():
    project_version = (Path(__file__).parents[1] / "VERSION").read_text().strip()

    assert re.fullmatch(r"\d+\.\d+\.\d+", project_version)


def test_pinned_runtime_versions():
    assert django.get_version() == "4.2.16"
    assert version("langgraph") == "1.2.10"
    assert version("langchain") == "1.3.14"


def test_django_runtime_passes_system_checks():
    result = subprocess.run(
        [sys.executable, "manage.py", "check"],
        capture_output=True,
        cwd=Path(__file__).parents[1],
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
