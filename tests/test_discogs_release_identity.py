import unittest

from discogs_matching import release_id, rejected_release


class DiscogsReleaseIdentityTests(unittest.TestCase):
    def test_current_and_historical_urls_identify_the_same_release(self):
        for url in (
            'https://www.discogs.com/release/514557',
            'https://discogs.com/release/514557-Old-Slug/',
            'https://www.discogs.com/Artist-Title/release/514557',
        ):
            self.assertEqual(release_id(url), 514557)

    def test_historical_reviewed_rejection_blocks_canonical_replay(self):
        old={'platform_matches':{'discogs':{'reason':'reviewed_rejection',
            'rejected_url':'https://www.discogs.com/Artist-Title/release/514557'}}}
        self.assertTrue(rejected_release(old,'https://www.discogs.com/release/514557-New-Slug'))
        self.assertFalse(rejected_release(old,'https://www.discogs.com/release/514558'))

    def test_untrusted_hosts_or_resource_types_are_not_release_identities(self):
        for url in ('https://example.com/release/514557',
                    'https://www.discogs.com.evil.invalid/release/514557',
                    'https://www.discogs.com/master/514557',
                    'https://www.discogs.com/release/514557?redirect=elsewhere',
                    'https://www.discogs.com/one/two/release/514557'):
            self.assertIsNone(release_id(url))


if __name__ == '__main__':
    unittest.main()
