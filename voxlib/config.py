"""
Loads settings from a YAML config file, so you don't have to repeat the same
command-line flags on every regular run.

Priority: explicit command-line flags > config file values > defaults.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import validation


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

    # A config value never passes through argparse's own type= conversion, so
    # the numeric checks have to be applied here too — from voxlib/validation.py,
    # the same module main.py's argparse types wrap, so the two entry points
    # can't drift apart.
    for key, validator in (
        ("threshold", validation.cosine_threshold),
        ("low_confidence_threshold", validation.logprob_threshold),
        ("split_chars", validation.positive_int),
        ("batch_size", validation.positive_int),
    ):
        if raw.get(key) is not None:
            try:
                raw[key] = validator(raw[key], key)
            except ValueError as exc:
                raise ValueError(f"In config {config_path}: {exc}") from exc

    # reference and output_dir are more convenient to specify as path strings in the config
    if "reference" in raw and raw["reference"] is not None:
        raw["reference"] = Path(raw["reference"])
    if "output_dir" in raw and raw["output_dir"] is not None:
        raw["output_dir"] = Path(raw["output_dir"])
    if "log_file" in raw and raw["log_file"] is not None:
        raw["log_file"] = Path(raw["log_file"])

    return raw
