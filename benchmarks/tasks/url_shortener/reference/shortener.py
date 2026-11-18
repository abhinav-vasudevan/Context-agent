from codec import encode_base62


class Shortener:
    def __init__(self):
        self._counter = 0
        self._by_url = {}
        self._by_code = {}
        self._clicks = {}

    def shorten(self, url):
        if not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        if url in self._by_url:
            return self._by_url[url]
        self._counter += 1
        code = encode_base62(self._counter)
        self._by_url[url] = code
        self._by_code[code] = url
        self._clicks[code] = 0
        return code

    def expand(self, code):
        url = self._by_code[code]
        self._clicks[code] += 1
        return url

    def clicks(self, code):
        return self._clicks[code]
