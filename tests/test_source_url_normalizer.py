import unittest

from source_url_normalizer import (
    clean_soundcloud_url,
    is_soundcloud_short_url,
    resolve_canonical_source_url,
)


class FakeResponse:
    def __init__(self, url):
        self._url = url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def geturl(self):
        return self._url


class SourceUrlNormalizerTests(unittest.TestCase):
    def test_detects_soundcloud_short_urls(self):
        self.assertTrue(is_soundcloud_short_url("https://on.soundcloud.com/lMS932ioS3yPO7fuGe"))
        self.assertTrue(is_soundcloud_short_url("https://snd.sc/example"))
        self.assertFalse(is_soundcloud_short_url("https://soundcloud.com/djulz/example"))

    def test_cleans_soundcloud_share_params(self):
        self.assertEqual(
            "https://soundcloud.com/djulz/djulz-refuge-ny-24-01-26?secret_token=s-test",
            clean_soundcloud_url(
                "https://soundcloud.com/djulz/djulz-refuge-ny-24-01-26"
                "?ref=clipboard&si=abc&utm_source=clipboard&secret_token=s-test"
            ),
        )

    def test_resolves_soundcloud_short_urls_to_canonical_urls(self):
        def fake_urlopen(request, timeout):
            return FakeResponse(
                "https://soundcloud.com/djulz/djulz-refuge-ny-24-01-26"
                "?ref=clipboard&p=i&c=0&si=abc&utm_source=clipboard"
            )

        self.assertEqual(
            "https://soundcloud.com/djulz/djulz-refuge-ny-24-01-26",
            resolve_canonical_source_url(
                "https://on.soundcloud.com/lMS932ioS3yPO7fuGe",
                opener=fake_urlopen,
            ),
        )


if __name__ == "__main__":
    unittest.main()
