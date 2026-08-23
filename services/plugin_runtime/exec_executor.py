import json
from pathlib import Path
import subprocess
import sys

from django.conf import settings


class ExecExecutionError(RuntimeError):
    pass


class UnsafeScriptPathError(ExecExecutionError):
    pass


class ExecExecutor:
    def __init__(self, allowlist=None):
        self.project_root = Path(settings.BASE_DIR).resolve()
        self.allowlist = Path(allowlist or self.project_root / "plugins" / "exec").resolve()

    def execute(self, capability_version, payload):
        script = self._script_path(capability_version.script_path)
        try:
            completed = subprocess.run(
                [sys.executable, str(script), json.dumps(payload)],
                capture_output=True,
                check=False,
                shell=False,
                text=True,
                timeout=capability_version.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExecExecutionError("EXEC plugin timed out") from exc

        if completed.returncode:
            raise ExecExecutionError(f"EXEC plugin exited with status {completed.returncode}")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ExecExecutionError("EXEC plugin stdout must be JSON") from exc

    def _script_path(self, script_path):
        if not script_path:
            raise UnsafeScriptPathError("EXEC plugin requires a script path in the allowlist")
        candidate = Path(script_path)
        if ".." in candidate.parts:
            raise UnsafeScriptPathError("EXEC script traversal is not allowed")
        resolved = (candidate if candidate.is_absolute() else self.project_root / candidate).resolve()
        try:
            resolved.relative_to(self.allowlist)
        except ValueError as exc:
            raise UnsafeScriptPathError("EXEC script is outside the allowlist") from exc
        if resolved.suffix != ".py" or not resolved.is_file():
            raise UnsafeScriptPathError("EXEC script must be an existing Python file in the allowlist")
        return resolved
