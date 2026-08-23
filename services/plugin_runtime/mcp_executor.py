class McpExecutionError(RuntimeError):
    pass


class McpExecutor:
    def __init__(self, adapter=None):
        self.adapter = adapter

    def execute(self, capability_version, payload):
        if self.adapter is None:
            raise McpExecutionError("MCP requires a test adapter")
        return self.adapter.execute(
            capability_version.mcp_server,
            capability_version.mcp_tool,
            payload,
            capability_version.timeout_seconds,
        )
