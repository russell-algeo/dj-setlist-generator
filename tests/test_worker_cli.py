import unittest

from worker.cli import _parse_args


class WorkerCliParseArgsTests(unittest.TestCase):
    def test_parses_url_target_without_treating_it_as_subcommand(self):
        args = _parse_args(["https://example.com/set"])

        self.assertIsNone(args.subcommand)
        self.assertEqual(args.targets, ["https://example.com/set"])
        self.assertFalse(args.local)

    def test_parses_auth_login_subcommand(self):
        args = _parse_args(["auth", "login", "--token", "sl_test_token"])

        self.assertEqual(args.subcommand, "auth")
        self.assertEqual(args.auth_command, "login")
        self.assertEqual(args.token, "sl_test_token")


if __name__ == "__main__":
    unittest.main()
