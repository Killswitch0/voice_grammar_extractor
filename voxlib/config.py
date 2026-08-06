"""
Loads settings from a YAML config file, so you don't have to repeat the same
command-line flags on every regular run.

Priority: explicit command-line flags > config file values > defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


# Keys allowed in the config file — match the argparse dest names.
ALLOWED_KEYS = {
    "reference",
    "output_dir",
    "hf_token",
    "whisper_model",
    "language",
    "device",
    "threshold",
    "no_diarization",
    "split_chars",
    "low_confidence_threshold",
    "remove_fillers",
    "batch_size",
    "log_file",
}


def load_config(config_path: Path) -> dict[str, Any]:
    import yaml

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"Config {config_path} must be a YAML mapping (key: value)")

    unknown = set(raw.keys()) - ALLOWED_KEYS
    if unknown:
        raise ValueError(
            f"Unknown keys in config {config_path}: {sorted(unknown)}. "
            f"Allowed keys: {sorted(ALLOWED_KEYS)}"
        )

    # A cosine similarity, mathematically bounded to [-1.0, 1.0] (see
    # DiarizationEngine.cosine_similarity) — the same check argparse applies
    # to --threshold on the command line, applied here too since a config
    # value never goes through argparse's own type= conversion.
    if "threshold" in raw and raw["threshold"] is not None:
        threshold = raw["threshold"]
        if not (-1.0 <= threshold <= 1.0):
            raise ValueError(
                f"threshold in config {config_path} must be between -1.0 and 1.0, got {threshold}"
            )

    # reference and output_dir are more convenient to specify as path strings in the config
    if "reference" in raw and raw["reference"] is not None:
        raw["reference"] = Path(raw["reference"])
    if "output_dir" in raw and raw["output_dir"] is not None:
        raw["output_dir"] = Path(raw["output_dir"])
    if "log_file" in raw and raw["log_file"] is not None:
        raw["log_file"] = Path(raw["log_file"])

    return raw
