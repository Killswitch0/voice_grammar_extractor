"""
The point of these: every setting has two entry points — a CLI flag and a YAML
key — and they must accept and reject exactly the same values. Before
voxlib/validation.py existed, only argparse checked anything, so a config file
could smuggle in a value the command line would have rejected outright.
"""

import pytest

import main
from voxlib import validation
from voxlib.config import load_config


def _config(tmp_path, body: str):
    path = tmp_path / "c.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_cosine_threshold_rejects_values_outside_the_similarity_range():
    assert validation.cosine_threshold("0.8") == 0.8
    assert validation.cosine_threshold(-1.0) == -1.0

    with pytest.raises(ValueError, match="cosine similarity"):
        validation.cosine_threshold(8.0)  # "0.8" typed without the decimal point


def test_logprob_threshold_rejects_positive_values():
    """
    A positive avg_logprob threshold marks EVERY line as low-confidence, and
    the analysis workflow excludes [?] lines from grammar judgment entirely —
    so it wouldn't error, it would quietly empty the review.
    """
    assert validation.logprob_threshold("-0.5") == -0.5

    with pytest.raises(ValueError, match="avg_logprob"):
        validation.logprob_threshold(0.5)
    with pytest.raises(ValueError, match="avg_logprob"):
        validation.logprob_threshold(-50.0)


def test_positive_int_rejects_zero_and_fractions():
    assert validation.positive_int("8", "--batch-size") == 8
    assert validation.positive_int(8, "--batch-size") == 8

    # 0 is falsy, so it used to silently turn the feature off instead of
    # reporting that the value made no sense.
    with pytest.raises(ValueError, match="greater than 0"):
        validation.positive_int(0, "--batch-size")
    with pytest.raises(ValueError, match="greater than 0"):
        validation.positive_int(-3, "--split-chars")
    # int(8.5) would truncate to 8 rather than complain.
    with pytest.raises(ValueError, match="whole number"):
        validation.positive_int(8.5, "--batch-size")


def test_cli_rejects_a_bad_threshold(capsys):
    with pytest.raises(SystemExit):
        main.build_arg_parser().parse_args(["call.webm", "--threshold", "8.0"])
    assert "cosine similarity" in capsys.readouterr().err


def test_cli_rejects_a_bad_low_confidence_threshold(capsys):
    with pytest.raises(SystemExit):
        main.build_arg_parser().parse_args(["call.webm", "--low-confidence-threshold", "0.5"])
    assert "avg_logprob" in capsys.readouterr().err


def test_cli_rejects_a_zero_batch_size(capsys):
    with pytest.raises(SystemExit):
        main.build_arg_parser().parse_args(["call.webm", "--batch-size", "0"])
    assert "greater than 0" in capsys.readouterr().err


@pytest.mark.parametrize(
    "body, expected",
    [
        ("threshold: 8.0", "cosine similarity"),
        ("low_confidence_threshold: 0.5", "avg_logprob"),
        ("batch_size: 0", "greater than 0"),
        ("split_chars: -100", "greater than 0"),
    ],
)
def test_config_rejects_everything_the_cli_rejects(tmp_path, body, expected):
    with pytest.raises(ValueError, match=expected):
        load_config(_config(tmp_path, body))


def test_config_error_names_the_offending_file(tmp_path):
    with pytest.raises(ValueError, match="c.yaml"):
        load_config(_config(tmp_path, "threshold: 8.0"))


def test_valid_config_values_survive_validation(tmp_path):
    config = load_config(_config(tmp_path, "threshold: 0.8\nbatch_size: 8\nsplit_chars: 15000\n"))

    assert config["threshold"] == 0.8
    assert config["batch_size"] == 8
    assert config["split_chars"] == 15000
