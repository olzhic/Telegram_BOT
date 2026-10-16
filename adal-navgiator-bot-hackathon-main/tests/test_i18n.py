from app.i18n import STRINGS, detect_language


def test_translation_keys_are_complete():
    assert set(STRINGS["ru"]) == set(STRINGS["kk"])


def test_detects_kazakh_letters_and_defaults_to_russian():
    assert detect_language("Қоқыс шығарылмады") == "kk"
    assert detect_language("Не вывезли мусор") == "ru"
