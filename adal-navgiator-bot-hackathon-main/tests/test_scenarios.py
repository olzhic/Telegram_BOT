from app.domain.scenarios import is_almaty


def test_city_detection_accepts_almaty_forms_only():
    assert is_almaty("Алматы")
    assert is_almaty("г. Алматы")
    assert is_almaty("В Алматы")
    assert is_almaty("Almaty")
    assert not is_almaty("Астана")
    assert not is_almaty("Алматы облысы")
