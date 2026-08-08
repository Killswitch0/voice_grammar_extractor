from pathlib import Path

from voxlib import cache

EMPTY = {"diarization": None, "identification": None, "transcription": []}


def _make_input_file(tmp_path: Path, content: bytes = b"fake audio data") -> Path:
    f = tmp_path / "rec.wav"
    f.write_bytes(content)
    return f


def test_load_cache_missing_file_returns_empty(tmp_path: Path):
    input_file = _make_input_file(tmp_path)
    result = cache.load_cache(tmp_path / ".cache", input_file, mode="diarization")
    assert result == EMPTY


def test_save_then_load_round_trips(tmp_path: Path):
    input_file = _make_input_file(tmp_path)
    cache_dir = tmp_path / ".cache"

    cache.save_cache(cache_dir, input_file, mode="diarization", cache_data={
        "diarization": [{"start": 0.0, "end": 1.0, "speaker_label": "SPEAKER_00"}],
        "identification": None,
        "transcription": [],
    })

    loaded = cache.load_cache(cache_dir, input_file, mode="diarization")
    assert loaded["diarization"] == [{"start": 0.0, "end": 1.0, "speaker_label": "SPEAKER_00"}]
    assert loaded["identification"] is None
    assert loaded["transcription"] == []


def test_save_cache_leaves_no_tmp_file_behind(tmp_path: Path):
    input_file = _make_input_file(tmp_path)
    cache_dir = tmp_path / ".cache"

    cache.save_cache(cache_dir, input_file, mode="diarization", cache_data=EMPTY)

    assert list(cache_dir.glob("*.tmp")) == []
    # The exact file name is cache.py's business (it carries a path hash, see
    # _cache_path) — what matters here is that exactly one cache file landed
    # and no temp file was left next to it.
    written = list(cache_dir.glob("*.json"))
    assert len(written) == 1
    assert written[0].stem.startswith("rec_")


def test_same_stem_with_different_extensions_do_not_share_a_cache_file(tmp_path: Path):
    """
    `part_01.webm` and `part_01.m4a` in one folder used to map onto a single
    `part_01.json`. Because each one's fingerprint check then failed against
    the other's, they took turns resetting each other's diarization on every
    run — the most expensive step, silently redone forever.
    """
    cache_dir = tmp_path / ".cache"
    webm = tmp_path / "part_01.webm"
    webm.write_bytes(b"webm audio")
    m4a = tmp_path / "part_01.m4a"
    m4a.write_bytes(b"m4a audio, a different length entirely")

    webm_data = {"diarization": [{"start": 0.0, "end": 1.0, "speaker_label": "SPEAKER_00"}],
                 "identification": None, "transcription": []}
    m4a_data = {"diarization": [{"start": 5.0, "end": 6.0, "speaker_label": "SPEAKER_01"}],
                "identification": None, "transcription": []}

    cache.save_cache(cache_dir, webm, mode="diarization", cache_data=webm_data)
    cache.save_cache(cache_dir, m4a, mode="diarization", cache_data=m4a_data)

    assert len(list(cache_dir.glob("*.json"))) == 2
    # Neither write clobbered the other, and neither read is treated as stale.
    assert cache.load_cache(cache_dir, webm, mode="diarization")["diarization"] == webm_data["diarization"]
    assert cache.load_cache(cache_dir, m4a, mode="diarization")["diarization"] == m4a_data["diarization"]


def test_cache_is_invalidated_when_input_file_changes(tmp_path: Path):
    input_file = _make_input_file(tmp_path)
    cache_dir = tmp_path / ".cache"

    cache.save_cache(cache_dir, input_file, mode="diarization", cache_data={
        "diarization": [{"start": 0.0, "end": 1.0, "speaker_label": "SPEAKER_00"}],
        "identification": None,
        "transcription": [],
    })
    assert cache.load_cache(cache_dir, input_file, mode="diarization")["diarization"] is not None

    # Different size -> different fingerprint -> cache must reset, not crash.
    input_file.write_bytes(b"a completely different, longer chunk of fake audio bytes")
    assert cache.load_cache(cache_dir, input_file, mode="diarization") == EMPTY


def test_load_cache_ignores_corrupted_json(tmp_path: Path):
    input_file = _make_input_file(tmp_path)
    cache_dir = tmp_path / ".cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "rec.json").write_text("not valid json {{{")

    assert cache.load_cache(cache_dir, input_file, mode="diarization") == EMPTY


def test_cache_is_invalidated_when_mode_differs():
    # This is the regression case for a real bug: a file first processed in
    # --no-diarization (solo) mode caches a transcription containing EVERY
    # speaker. If that same file is later reprocessed with diarization +
    # --reference, the solo-mode transcription must NOT be reused — otherwise
    # the other speaker's lines silently leak into the "mine only" output.
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        tmp_path = Path(d)
        input_file = _make_input_file(tmp_path)
        cache_dir = tmp_path / ".cache"

        cache.save_cache(cache_dir, input_file, mode="solo", cache_data={
            "diarization": None,
            "identification": None,
            "transcription": [
                {"start": 0.0, "end": 1.0, "text": "line from me"},
                {"start": 1.0, "end": 2.0, "text": "line from the other speaker"},
            ],
        })

        # Loading in solo mode again still sees the cached (contaminated-by-design) data.
        solo_reload = cache.load_cache(cache_dir, input_file, mode="solo")
        assert len(solo_reload["transcription"]) == 2

        # Loading the SAME file in diarization mode must reset, not inherit
        # the solo-mode transcription.
        diarization_reload = cache.load_cache(cache_dir, input_file, mode="diarization")
        assert diarization_reload == EMPTY


def test_reference_change_resets_identification_and_transcription_but_keeps_diarization(tmp_path: Path):
    input_file = _make_input_file(tmp_path)
    cache_dir = tmp_path / ".cache"
    ref_fp_1 = {"size": 100, "mtime": 1.0}
    ref_fp_2 = {"size": 200, "mtime": 2.0}  # a different reference voice sample

    cache.save_cache(cache_dir, input_file, mode="diarization", cache_data={
        "diarization": [{"start": 0.0, "end": 1.0, "speaker_label": "SPEAKER_00"}],
        "identification": [{"start": 0.0, "end": 1.0, "is_me": True, "similarity": 0.9}],
        "transcription": [{"start": 0.0, "end": 1.0, "text": "hello"}],
    }, reference_fingerprint=ref_fp_1)

    # Same reference -> everything reused.
    same_ref = cache.load_cache(cache_dir, input_file, mode="diarization", reference_fingerprint=ref_fp_1)
    assert same_ref["diarization"] is not None
    assert same_ref["identification"] is not None
    assert same_ref["transcription"] != []

    # Different reference -> identification + transcription reset, diarization kept.
    different_ref = cache.load_cache(cache_dir, input_file, mode="diarization", reference_fingerprint=ref_fp_2)
    assert different_ref["diarization"] is not None
    assert different_ref["identification"] is None
    assert different_ref["transcription"] == []


def test_transcription_params_change_resets_only_transcription(tmp_path: Path):
    input_file = _make_input_file(tmp_path)
    cache_dir = tmp_path / ".cache"
    params_small = {"whisper_model": "small", "language": "en", "batch_size": None}
    params_medium = {"whisper_model": "medium", "language": "en", "batch_size": None}

    cache.save_cache(cache_dir, input_file, mode="diarization", cache_data={
        "diarization": [{"start": 0.0, "end": 1.0, "speaker_label": "SPEAKER_00"}],
        "identification": [{"start": 0.0, "end": 1.0, "is_me": True, "similarity": 0.9}],
        "transcription": [{"start": 0.0, "end": 1.0, "text": "hello"}],
    }, transcription_params=params_small)

    # Same settings -> transcription reused.
    same_params = cache.load_cache(cache_dir, input_file, mode="diarization", transcription_params=params_small)
    assert same_params["transcription"] != []
    assert same_params["identification"] is not None

    # Different whisper model -> only transcription reset; diarization/identification kept.
    different_params = cache.load_cache(cache_dir, input_file, mode="diarization", transcription_params=params_medium)
    assert different_params["diarization"] is not None
    assert different_params["identification"] is not None
    assert different_params["transcription"] == []


def test_file_fingerprint_is_public_and_reusable_for_any_file(tmp_path: Path):
    f = tmp_path / "voice_reference.wav"
    f.write_bytes(b"some reference audio")
    fp = cache.file_fingerprint(f)
    assert fp == {"size": f.stat().st_size, "mtime": f.stat().st_mtime}


def test_segments_to_dicts_converts_dataclasses():
    from voxlib.diarization import Segment

    segments = [Segment(start=0.0, end=1.0, speaker_label="SPEAKER_00")]
    assert cache.segments_to_dicts(segments) == [
        {"start": 0.0, "end": 1.0, "speaker_label": "SPEAKER_00"}
    ]
