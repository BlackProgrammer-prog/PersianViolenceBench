"""Local TranslateGemma configuration, independent of paid translation settings."""

import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field

from pvb.translation.settings import ROOT


class LocalTranslationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    model_id: Literal["google/translategemma-4b-it"] = "google/translategemma-4b-it"
    model_path: Path = ROOT / "models/translategemma-4b"
    revision: str = "main"
    max_input_tokens: int = Field(default=2048, ge=64, le=2048)
    max_new_tokens: int = Field(default=512, ge=16, le=2048)
    allow_cpu_offload: bool = False
    gpu_reserve_mib: int = Field(default=256, ge=128)


def local_values(root=ROOT):
    values = dict(dotenv_values(root / ".env", interpolate=False))
    values.update(os.environ)
    return values


def load_local_settings(root=ROOT):
    values = local_values(root)
    fields = {
        "PVB_TRANSLATEGEMMA_MODEL_PATH": "model_path",
        "PVB_TRANSLATEGEMMA_REVISION": "revision",
        "PVB_TRANSLATEGEMMA_MAX_INPUT_TOKENS": "max_input_tokens",
        "PVB_TRANSLATEGEMMA_MAX_NEW_TOKENS": "max_new_tokens",
        "PVB_TRANSLATEGEMMA_ALLOW_CPU_OFFLOAD": "allow_cpu_offload",
        "PVB_TRANSLATEGEMMA_GPU_RESERVE_MIB": "gpu_reserve_mib",
    }
    kwargs = {dest: values[key] for key, dest in fields.items() if values.get(key)}
    if "model_path" in kwargs:
        kwargs["model_path"] = root / Path(kwargs["model_path"]).expanduser()
    return LocalTranslationSettings(**kwargs)
