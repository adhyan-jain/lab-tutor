from backend.socratic_engine import conversation


def test_bare_help_requests_are_openers():
    for m in ["can you help me", "Can you help me?", "hey, could you help me out please", "help", "I need help"]:
        assert conversation.is_help_opener(m), m


def test_real_questions_are_not_openers():
    for m in ["can you help me with the titration", "what is HOMO", "help me understand HOMO"]:
        assert not conversation.is_help_opener(m), m


def test_reply_is_warm_not_a_bare_yes():
    text = conversation.help_opener_text("Exp 7")
    assert not text.lower().startswith("yes")
    assert "right here" in text and "Exp 7" in text
