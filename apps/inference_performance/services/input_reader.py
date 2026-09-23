"""Server-created inputs for current evaluation and frozen inspection runs."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PerformanceInput:
    mode: str
    snapshot: Any = None
    frozen: dict | None = None


class InferenceSnapshotInputReader:
    source_type = 'INFERENCE_SNAPSHOT'

    def __init__(self, *, mode: str, assets=None, snapshot=None, frozen_inputs_by_asset=None, frozen_inputs=None):
        if mode not in {'COMPUTE', 'FROZEN_RESULT'}:
            raise ValueError('unsupported performance input mode')
        self.mode = mode
        self._assets = list(assets or [])
        self._snapshot = snapshot
        self._frozen = {str(key): value for key, value in (frozen_inputs_by_asset or frozen_inputs or {}).items()}

    def assets(self):
        return list(self._assets)

    def performance_input(self, asset_id):
        if self.mode == 'COMPUTE':
            if self._snapshot is None or str(getattr(self._snapshot, 'asset_id', None)) != str(asset_id):
                return None
            return PerformanceInput(mode='COMPUTE', snapshot=self._snapshot)
        value = self._frozen.get(str(asset_id))
        return PerformanceInput(mode='FROZEN_RESULT', frozen=value) if value else None
