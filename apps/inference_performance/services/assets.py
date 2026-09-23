"""Stable asset identity for externally supplied inference measurements."""

import hashlib
import json

from apps.assets.models import Asset


def inference_asset_key(engine_id: str, engine_type: str, model_name: str) -> str:
    encoded = json.dumps([engine_id, engine_type, model_name], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "inference:" + hashlib.sha256(encoded).hexdigest()


def get_or_create_inference_asset(*, environment, engine_id: str, engine_type: str, model_name: str) -> Asset:
    key = inference_asset_key(engine_id, engine_type, model_name)
    asset, _ = Asset.objects.get_or_create(
        environment=environment,
        external_key=key,
        defaults={
            "asset_type": Asset.AssetType.LLM_INSTANCE,
            "name": f"{engine_id} / {model_name}"[:192],
            "labels": {
                "input_source": "INFERENCE_SNAPSHOT",
                "engine_id": engine_id,
                "engine_type": engine_type,
                "model_name": model_name,
            },
        },
    )
    return asset
