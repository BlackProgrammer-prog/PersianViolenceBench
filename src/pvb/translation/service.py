"""Reusable, lazy, offline, serial English-to-Persian TranslateGemma inference."""

import gc
import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

from pvb.translation.local_settings import load_local_settings

log = logging.getLogger(__name__)
MANIFEST = "pvb_model_manifest.json"


class TranslationError(RuntimeError):
    """A translation could not be produced; no placeholder is returned."""


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_model_directory(path, *, verify_hashes=False):
    """Reject incomplete or changed local downloads before initializing CUDA."""
    path = Path(path)
    manifest_path = path / MANIFEST
    if not manifest_path.is_file():
        raise TranslationError("Model is not ready. Run the local download command first.")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("model_id") != "google/translategemma-4b-it":
        raise TranslationError("Local model manifest has an unexpected model ID.")
    if not manifest.get("commit_sha") or not manifest.get("files"):
        raise TranslationError("Local model manifest is incomplete.")
    for entry in manifest["files"]:
        target = (path / entry["path"]).resolve()
        if not target.is_relative_to(path.resolve()) or not target.is_file():
            raise TranslationError("Local model download is incomplete.")
        if target.stat().st_size != entry["size"]:
            raise TranslationError("Local model file size changed; recheck the download.")
        if verify_hashes and file_sha256(target) != entry["sha256"]:
            raise TranslationError("Local model checksum failed.")
    required = {entry["path"] for entry in manifest["files"]}
    if not {"config.json", "tokenizer_config.json", "tokenizer.json"}.issubset(required):
        raise TranslationError("Local model configuration/tokenizer is incomplete.")
    index = path / "model.safetensors.index.json"
    if index.exists():
        shards = set(json.loads(index.read_text())["weight_map"].values())
        if not shards.issubset(required):
            raise TranslationError("Local model is missing weight shards.")
    elif "model.safetensors" not in required:
        raise TranslationError("Local model has no complete weights.")
    return manifest


class TranslationService:
    def __init__(self, settings=None):
        self.settings = settings or load_local_settings()
        self._lock = threading.Lock()
        self._model = self._processor = self._torch = None
        self.load_metrics = None
        self.last_metrics = None
        self.manifest = None

    def memory(self):
        torch = self._torch
        if torch is None or not torch.cuda.is_available():
            return {}
        free, total = torch.cuda.mem_get_info()
        return {
            "gpu_free_bytes": free,
            "gpu_total_bytes": total,
            "allocated_bytes": torch.cuda.memory_allocated(),
            "reserved_bytes": torch.cuda.memory_reserved(),
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(),
        }

    def _load(self):
        if self._model is not None:
            return
        self.manifest = validate_model_directory(self.settings.model_path)
        # Set before importing Hugging Face/Transformers. All loads also explicitly disallow network.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        import torch
        import transformers
        from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig

        self._torch = torch
        if not torch.cuda.is_available():
            raise TranslationError(
                "CUDA is unavailable; inspect the NVIDIA driver and PyTorch build."
            )
        dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        torch.cuda.synchronize()
        started = time.perf_counter()
        before = self.memory()
        free = before["gpu_free_bytes"]
        reserve = self.settings.gpu_reserve_mib * 1024**2
        if free < reserve + 1024**3:
            raise TranslationError(
                "Insufficient free GPU memory; close GPU applications and retry."
            )
        quantization = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype,
            llm_int8_enable_fp32_cpu_offload=self.settings.allow_cpu_offload,
        )
        options = {}
        if self.settings.allow_cpu_offload:
            # Use current free RAM, not total host memory. CPU modules may be unquantized.
            import psutil

            ram = psutil.virtual_memory().available
            options["max_memory"] = {
                0: free - reserve,
                "cpu": max(0, ram - 512 * 1024**2),
            }
        try:
            processor = AutoProcessor.from_pretrained(
                str(self.settings.model_path), local_files_only=True
            )
            model = AutoModelForImageTextToText.from_pretrained(
                str(self.settings.model_path),
                local_files_only=True,
                quantization_config=quantization,
                device_map="auto" if self.settings.allow_cpu_offload else {"": 0},
                torch_dtype=dtype,
                low_cpu_mem_usage=True,
                attn_implementation="sdpa",
                **options,
            )
            model.eval()
            torch.cuda.synchronize()
        except (RuntimeError, ValueError) as exc:
            gc.collect()
            torch.cuda.empty_cache()
            raise TranslationError(
                "NF4 model loading failed. Check free GPU/RAM and CPU offload settings. "
                + type(exc).__name__
                + ": "
                + str(exc)[:600]
            ) from exc
        self._processor, self._model = processor, model
        self.load_metrics = {
            "placement_policy": (
                "gpu_first_with_cpu_fallback" if self.settings.allow_cpu_offload else "gpu_only"
            ),
            "gpu_reserve_mib": self.settings.gpu_reserve_mib,
            "seconds": time.perf_counter() - started,
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "gpu": torch.cuda.get_device_name(0),
            "compute_dtype": str(dtype),
            "quantization": "nf4_double_quant_4bit",
            "device_map": {k: str(v) for k, v in model.hf_device_map.items()},
            "memory_before": before,
            "memory_after": self.memory(),
        }
        log.info("TranslateGemma loaded: %s", self.load_metrics)

    def load(self):
        with self._lock:
            self._load()
        return self.load_metrics

    def translate(self, text: str) -> str:
        if not isinstance(text, str):
            raise TypeError("Translation input must be a string.")
        if not text.strip():
            return text
        with self._lock:
            self._load()
            torch, processor, model = self._torch, self._processor, self._model
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "source_lang_code": "en",
                            "target_lang_code": "fa",
                            "text": text,
                        }
                    ],
                }
            ]
            inputs = processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
            length = inputs["input_ids"].shape[-1]
            if length > self.settings.max_input_tokens:
                raise TranslationError(
                    f"Input has {length} tokens; limit is {self.settings.max_input_tokens}. "
                    "Text was not silently truncated."
                )
            inputs = inputs.to(model.device)
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
            start = time.perf_counter()
            try:
                with torch.inference_mode():
                    result = model.generate(
                        **inputs,
                        do_sample=False,
                        max_new_tokens=self.settings.max_new_tokens,
                        use_cache=True,
                    )
                torch.cuda.synchronize()
                generated = result[0][length:]
                text_out = processor.decode(generated, skip_special_tokens=True).strip()
                eos = model.generation_config.eos_token_id
                eos = [eos] if isinstance(eos, int) else eos or []
                truncated = (
                    len(generated) >= self.settings.max_new_tokens and int(generated[-1]) not in eos
                )
                self.last_metrics = {
                    "seconds": time.perf_counter() - start,
                    "input_tokens": length,
                    "output_tokens": len(generated),
                    "truncated": truncated,
                    "memory": self.memory(),
                }
                if truncated:
                    raise TranslationError(
                        "Output hit its token limit; no partial translation saved."
                    )
                if not text_out:
                    raise TranslationError("Model produced an empty translation.")
                log.info("TranslateGemma translated: %s", self.last_metrics)
                return text_out
            except torch.cuda.OutOfMemoryError as exc:
                torch.cuda.empty_cache()
                raise TranslationError(
                    "CUDA out of memory with batch size 1; free GPU memory before retrying."
                ) from exc

    def translate_batch(self, texts: list[str]) -> list[str]:
        # Intentionally serial: one loaded model and one generation on this GPU at a time.
        return [self.translate(text) for text in texts]
