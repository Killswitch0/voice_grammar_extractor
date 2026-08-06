import main


def test_threshold_defaults_to_none_without_config_or_flag():
    args = main.build_arg_parser().parse_args(["call.webm"])
    assert args.threshold is None


def test_explicit_threshold_flag_is_used():
    args = main.build_arg_parser().parse_args(["call.webm", "--threshold", "0.6"])
    assert args.threshold == 0.6


def test_config_threshold_is_used_when_flag_not_given():
    args = main.build_arg_parser({"threshold": 0.6}).parse_args(["call.webm"])
    assert args.threshold == 0.6


def test_explicit_flag_overrides_config():
    args = main.build_arg_parser({"threshold": 0.6}).parse_args(["call.webm", "--threshold", "0.9"])
    assert args.threshold == 0.9
