from flightbot.core.places import normalize, place_name, search_static


def test_normalize_handles_azerbaijani_letters():
    assert normalize("Bakı") == normalize("baki") == "baki"
    assert normalize("İstanbul") == "istanbul"
    assert normalize("Şəki") == "seki"


def test_search_by_name_any_language():
    assert search_static("Bakı")[0].code == "GYD"
    assert search_static("Баку")[0].code == "GYD"
    assert search_static("istan")[0].code == "IST"
    assert search_static("Стамб")[0].code == "IST"


def test_search_by_iata_code_exact_first():
    assert search_static("ist")[0].code == "IST"
    assert search_static("DXB")[0].code == "DXB"


def test_empty_and_unknown():
    assert search_static("") == []
    assert search_static("zzzzqq") == []


def test_place_name_languages_and_fallback():
    assert place_name("GYD", "az") == "Bakı"
    assert place_name("GYD", "ru") == "Баку"
    assert place_name("GYD", "en") == "Baku"
    assert place_name("XXX", "az") == "XXX"
