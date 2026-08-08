from voxlib.filler_filter import remove_fillers


def test_removes_pure_filler_sounds():
    assert remove_fillers("Um, I think so") == "I think so"
    assert remove_fillers("uh uh I dont know") == "I dont know"
    assert remove_fillers("It's, erm, complicated") == "It's, complicated"


def test_case_insensitive_and_repeated_letters():
    assert remove_fillers("Umm, wait") == "wait"
    assert remove_fillers("Uhhh, wait") == "wait"
    # This used to assert remove_fillers("UH huh, sure") == "huh, sure", which
    # encoded the backchannel bug as expected behavior — see
    # test_backchannel_uh_huh_is_left_intact below.
    assert remove_fillers("ERM, wait") == "wait"


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


def test_backchannel_uh_huh_is_left_intact():
    """
    "uh-huh" is agreement, not hesitation — the spoken equivalent of a nod.
    Stripping the "uh" out of it used to yield "-huh", i.e. a broken line
    invented by the tool inside a document meant for grammar review.
    """
    assert remove_fillers("Uh-huh, I agree") == "Uh-huh, I agree"
    assert remove_fillers("uh huh, that's right") == "uh huh, that's right"
    assert remove_fillers("Mm-hmm.") == "Mm-hmm."


def test_hesitation_is_still_removed_next_to_a_backchannel():
    assert remove_fillers("uh-huh uh I mean") == "uh-huh I mean"
