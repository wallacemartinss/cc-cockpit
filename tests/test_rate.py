import io
import json
import unittest
from unittest.mock import patch

from cockpit import rate


def reply(body, status=200):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    r = Response(body if isinstance(body, bytes) else json.dumps(body).encode())
    r.status = status
    return r


class ParseTests(unittest.TestCase):
    def test_sgs_reply(self):
        self.assertEqual(rate.parse([{"data": "25/09/2026", "valor": "5.1991"}]),
                         (5.1991, "25/09/2026"))

    def test_last_row_wins(self):
        rows = [{"data": "24/09/2026", "valor": "5.1795"}, {"data": "25/09/2026", "valor": "5.1991"}]
        self.assertEqual(rate.parse(rows), (5.1991, "25/09/2026"))

    def test_decimal_comma(self):
        self.assertEqual(rate.parse([{"data": "25/09/2026", "valor": "5,1991"}])[0], 5.1991)

    def test_anything_else_is_refused(self):
        for body in ([], {}, "5.19", [{"data": "x"}], [{"valor": "abc", "data": "x"}],
                     [{"valor": "0", "data": "x"}], [{"valor": "-1", "data": "x"}], None):
            with self.assertRaises(rate.RateError, msg=repr(body)):
                rate.parse(body)


class UrlTests(unittest.TestCase):
    def test_default_until_changed(self):
        self.assertEqual(rate.url_for({}), rate.DEFAULT_URL)
        self.assertEqual(rate.url_for({"rate_url": None}), rate.DEFAULT_URL)
        self.assertEqual(rate.url_for({"rate_url": "https://x.example/api"}), "https://x.example/api")

    def test_stored_only_when_it_differs(self):
        self.assertIsNone(rate.stored_url(rate.DEFAULT_URL))
        self.assertIsNone(rate.stored_url("  "))
        self.assertEqual(rate.stored_url(" https://x.example/api "), "https://x.example/api")

    def test_only_https(self):
        for url in ("http://api.bcb.gov.br/x", "file:///etc/passwd", "ftp://x", "api.bcb.gov.br"):
            with self.assertRaises(rate.RateError, msg=url):
                rate.fetch(url)


class FetchTests(unittest.TestCase):
    def test_fetch_reads_the_reply(self):
        with patch("cockpit.rate.urllib.request.urlopen",
                   return_value=reply([{"data": "25/09/2026", "valor": "5.1991"}])) as urlopen:
            self.assertEqual(rate.fetch(), (5.1991, "25/09/2026"))
        request, = urlopen.call_args.args
        self.assertEqual(request.full_url, rate.DEFAULT_URL)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], rate.TIMEOUT)

    def test_network_failure_becomes_a_rate_error(self):
        import urllib.error
        with patch("cockpit.rate.urllib.request.urlopen",
                   side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(rate.RateError):
                rate.fetch()

    def test_not_json_becomes_a_rate_error(self):
        with patch("cockpit.rate.urllib.request.urlopen", return_value=reply(b"<html>")):
            with self.assertRaises(rate.RateError):
                rate.fetch()

    def test_oversized_reply_is_refused(self):
        with patch("cockpit.rate.urllib.request.urlopen",
                   return_value=reply(b"[" + b" " * (rate.MAX_BYTES + 10) + b"]")):
            with self.assertRaises(rate.RateError):
                rate.fetch()


if __name__ == "__main__":
    unittest.main()
