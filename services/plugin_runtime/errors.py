class PluginExecutionError(RuntimeError):
    pass


class ReadOnlyCapabilityError(PluginExecutionError):
    pass
