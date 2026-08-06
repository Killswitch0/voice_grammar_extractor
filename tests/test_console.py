from voxlib.console import print_error


def test_print_error_does_not_mangle_bracketed_text(capsys):
    print_error("[Errno 2] No such file or directory: 'x.wav'")

    out = capsys.readouterr().out
    assert "[Errno 2]" in out


def test_print_error_writes_plain_line_to_log_file(tmp_path):
    log_file = tmp_path / "run.log"

    print_error("A HuggingFace token is required", log_file=log_file)

    content = log_file.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert len(lines) == 1
    assert "[ERROR]" in lines[0]
    assert "A HuggingFace token is required" in lines[0]
