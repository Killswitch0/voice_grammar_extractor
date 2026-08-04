from pathlib import Path

import pytest

from voxlib.config import load_config


def test_valid_config_loads_and_converts_paths(tmp_path: Path):
    p = tmp_path / "ok.yaml"
    p.write_text(
        "reference: my_voice.wav\n"
        "output_dir: output\n"
        "whisper_model: medium\n"
        "threshold: 0.8\n"
    )
    result = load_config(p)
    assert result["reference"] == Path("my_voice.wav")
    assert result["output_dir"] == Path("output")
    assert result["whisper_model"] == "medium"
    assert result["threshold"] == 0.8


def test_unknown_key_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("reference: x.wav\nnot_a_real_key: true\n")
    with pytest.raises(ValueError, match="Unknown keys"):
        load_config(p)


def test_removed_resume_key_is_no_longer_accepted(tmp_path: Path):
    # 'resume' used to be listed in ALLOWED_KEYS but was never wired up to any
    # flag — it was removed as dead config. This guards against it silently
    # being re-introduced without also being implemented.
    p = tmp_path / "resume.yaml"
    p.write_text("resume: true\n")
    with pytest.raises(ValueError, match="Unknown keys"):
        load_config(p)


def test_non_mapping_yaml_raises(tmp_path: Path):
    p = tmp_path / "notdict.yaml"
    p.write_text("- a\n- b\n")
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        load_config(p)


def test_empty_file_returns_empty_dict(tmp_path: Path):
    p = tmp_path / "empty.yaml"
    p.write_text("")
    assert load_config(p) == {}


def test_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.yaml")
