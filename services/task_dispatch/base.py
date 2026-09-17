from typing import Protocol


class TaskDispatcher(Protocol):
    def enqueue_manual_inspection(self, run_id: str) -> dict: ...

    def enqueue_resource_investigation(
        self,
        investigation_id: str,
        context: dict,
    ) -> dict: ...
