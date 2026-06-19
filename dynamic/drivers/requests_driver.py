"""Офлайн-драйвер для requests: задействует код библиотеки без сети.

sys.path и HOME настраиваются снаружи (оркестратором/запускающей командой):
  - в sys.path добавлены <instrumented>/ (для cqtrace) и <instrumented>/src (для requests);
  - HOME указывает на каталог трасс.
"""
import io


def exercise():
    import requests
    from requests import Request, Session
    from requests.models import Response, PreparedRequest
    from requests.structures import CaseInsensitiveDict
    from requests.cookies import RequestsCookieJar, cookiejar_from_dict
    from requests.auth import HTTPBasicAuth, HTTPDigestAuth, _basic_auth_str
    from requests import utils

    # --- подготовка запроса (PreparedRequest, кодирование URL/параметров) ---
    s = Session()
    for method in ("GET", "POST", "PUT", "DELETE", "HEAD"):
        req = Request(method, "https://example.com/a/b?x=1",
                      headers={"X-Test": "1"}, params={"q": "search term", "n": 5},
                      data={"f": "v"} if method in ("POST", "PUT") else None)
        p = s.prepare_request(req)
        _ = p.url, p.method, p.headers

    # --- структуры ---
    d = CaseInsensitiveDict()
    d["Content-Type"] = "text/html"
    _ = d["content-type"], "CONTENT-TYPE" in d, list(d.items()), repr(d)
    d.update({"Accept": "*/*"})

    # --- cookies ---
    jar = RequestsCookieJar()
    jar.set("k", "v", domain="example.com", path="/")
    _ = jar.get("k"), list(jar.keys()), dict(jar)
    cookiejar_from_dict({"a": "1", "b": "2"})

    # --- auth ---
    _ = _basic_auth_str("user", "pass")
    ba = HTTPBasicAuth("user", "pass")
    pr = s.prepare_request(Request("GET", "https://example.com/"))
    ba(pr)
    HTTPDigestAuth("user", "pass")

    # --- utils ---
    utils.requote_uri("https://example.com/path with space")
    utils.urldefragauth("https://u:p@example.com/p#frag")
    utils.parse_header_links('<https://x>; rel="next", <https://y>; rel="prev"')
    utils.get_encoding_from_headers({"content-type": "text/html; charset=utf-8"})
    utils.dict_from_cookiejar(jar)
    utils.default_headers()
    try:
        utils.guess_json_utf(b'{"a": 1}')
    except Exception:
        pass

    # --- модель ответа (json/text/ok) без сети ---
    r = Response()
    r.status_code = 200
    r.headers = CaseInsensitiveDict({"Content-Type": "application/json; charset=utf-8"})
    r._content = b'{"hello": "world", "n": 42}'
    r.encoding = "utf-8"
    r.url = "https://example.com/"
    _ = r.ok, r.text, r.json(), r.content, bool(r), r.apparent_encoding
    list(r.iter_content(chunk_size=8))

    r2 = Response()
    r2.status_code = 404
    try:
        r2.raise_for_status()
    except requests.exceptions.HTTPError:
        pass

    # --- разное ---
    requests.utils.address_in_network("192.168.1.1", "192.168.1.0/24")
    requests.utils.is_valid_cidr("10.0.0.0/8")


if __name__ == "__main__":
    exercise()
    print("requests driver: OK")
