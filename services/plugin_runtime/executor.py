from jsonschema import ValidationError, validate

from .exec_executor import ExecExecutor
from .mcp_executor import McpExecutor
from .rest_executor import RestExecutor
from .rule_executor import RuleExecutor


class PluginExecutionError(RuntimeError):
    pass


class InputValidationError(PluginExecutionError):
    pass


class ReadOnlyCapabilityError(PluginExecutionError):
    pass


class PluginExecutor:
    def __init__(self, *, rule_executor=None, exec_executor=None, rest_executor=None, mcp_executor=None):
        self.executors = {
            "RULE": rule_executor or RuleExecutor(),
            "EXEC": exec_executor or ExecExecutor(),
            "REST": rest_executor or RestExecutor(),
            "MCP": mcp_executor or McpExecutor(),
        }

    def execute(self, capability_version, payload, *, llm=False, origin=None):
        if llm or origin == "LLM":
            if not capability_version.capability.read_only:
                raise ReadOnlyCapabilityError("LLM execution requires a read-only capability")
        try:
            validate(payload, capability_version.input_schema)
        except ValidationError as exc:
            raise InputValidationError(f"input schema validation failed: {exc.message}") from exc

        try:
            executor = self.executors[capability_version.implementation_type]
        except KeyError as exc:
            raise PluginExecutionError("unsupported plugin implementation type") from exc
        return executor.execute(capability_version, payload)
