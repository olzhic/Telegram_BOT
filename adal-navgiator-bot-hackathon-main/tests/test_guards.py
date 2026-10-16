from app.ai.guards import RagAnswer, validate_answer


def test_unknown_citation_is_rejected():
    result = RagAnswer(supported=True, answer="Следуйте инструкции.", citations=["missing"])
    assert not validate_answer(result, {"known": "instruction"})


def test_empty_citations_are_rejected():
    result = RagAnswer(supported=True, answer="Следуйте инструкции.", citations=[])
    assert not validate_answer(result, {"known": "instruction"})


def test_ungrounded_phone_and_deadline_are_rejected():
    result = RagAnswer(
        supported=True,
        answer="Позвоните по номеру +7 777 123 45 67 в течение 15 дней.",
        citations=["source#0"],
    )
    assert not validate_answer(result, {"source#0": "Подайте обращение через официальный портал."})


def test_ungrounded_short_hotline_number_is_rejected():
    result = RagAnswer(
        supported=True,
        answer="Позвоните по номеру 109.",
        citations=["source#0"],
    )
    assert not validate_answer(result, {"source#0": "Подайте обращение через официальный портал."})


def test_grounded_answer_is_accepted():
    content = "Обратитесь по номеру 109."
    result = RagAnswer(supported=True, answer="Контакт: 109.", citations=["source#0"])
    assert validate_answer(result, {"source#0": content})


def test_unsupported_answer_is_rejected():
    result = RagAnswer(supported=False, answer="", citations=[])
    assert not validate_answer(result, {"source#0": "text"})
