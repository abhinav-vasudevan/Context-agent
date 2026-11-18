import pytest
from discover import load_symbol, run_main


def test_encode_known_values():
    enc = load_symbol("encode_base62")
    assert [enc(n) for n in (0, 9, 10, 35, 36, 61, 62, 3843)] == ["0", "9", "a", "z", "A", "Z", "10", "ZZ"]


def test_roundtrip_and_errors():
    enc = load_symbol("encode_base62")
    dec = load_symbol("decode_base62")
    for n in (1, 125, 99999, 2 ** 40):
        assert dec(enc(n)) == n
    with pytest.raises(ValueError):
        enc(-1)
    with pytest.raises(ValueError):
        dec("ab-c")
    with pytest.raises(ValueError):
        dec("")


def test_codes_follow_counter_and_dedupe():
    Shortener = load_symbol("Shortener")
    s = Shortener()
    a = s.shorten("https://a.com")
    b = s.shorten("http://b.com")
    again = s.shorten("https://a.com")
    c = s.shorten("https://c.com")
    assert (a, b, again, c) == ("1", "2", "1", "3")


def test_rejects_non_http_urls():
    Shortener = load_symbol("Shortener")
    with pytest.raises(ValueError):
        Shortener().shorten("ftp://files.example.com")


def test_expand_and_clicks():
    Shortener = load_symbol("Shortener")
    s = Shortener()
    code = s.shorten("https://example.com/page")
    assert s.clicks(code) == 0
    assert s.expand(code) == "https://example.com/page"
    s.expand(code)
    assert s.clicks(code) == 2
    with pytest.raises(KeyError):
        s.expand("zzz")
    with pytest.raises(KeyError):
        s.clicks("zzz")


def test_cli_end_to_end():
    out = run_main(
        "shorten https://example.com\nshorten https://python.org\nexpand 2\nexpand 2\n"
        "clicks 2\nshorten notaurl\nexpand 999\nquit\n"
    )
    assert out.returncode == 0, out.stderr
    lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    assert lines[:5] == ["1", "2", "https://python.org", "https://python.org", "2"]
    assert sum(ln.startswith("Error:") for ln in lines) == 2
