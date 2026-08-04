from voxlib.filler_filter import remove_fillers


def test_removes_pure_filler_sounds():
    assert remove_fillers("Um, I think so") == "I think so"
    assert remove_fillers("uh uh I dont know") == "I dont know"
    assert remove_fillers("It's, erm, complicated") == "It's, complicated"


def test_case_insensitive_and_repeated_letters():
    assert remove_fillers("Umm, wait") == "wait"
    assert remove_fillers("UH huh, sure") == "huh, sure"


def test_does_not_touch_meaningful_words():
    # These look like fillers but are fully meaningful in context — must survive untouched.
    assert remove_fillers("I like it") == "I like it"
    assert remove_fillers("you know what I mean") == "you know what I mean"
    # "umbrella" contains "um" but isn't the standalone word "um".
    assert remove_fillers("umbrella is red") == "umbrella is red"


def test_collapses_whitespace_and_duplicate_punctuation_left_behind():
    assert remove_fillers("So,, um, we left") == "So, we left"
    assert remove_fillers("Well   um   okay") == "Well okay"


def test_empty_and_filler_only_input():
    assert remove_fillers("") == ""
    assert remove_fillers("um") == ""


def test_unaffected_sentence_is_unchanged():
    assert remove_fillers("A perfectly normal sentence.") == "A perfectly normal sentence."
