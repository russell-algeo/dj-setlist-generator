import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from worker.callbacks import _NoRedirects, callback_headers, main, post_callback, validate_callback_settings
from worker.config import WorkerSettings

PREVIEW = 'https://dj-setlist-generator-listened-preview.vercel.app'


def settings(url=PREVIEW, secret='development-test-secret'):
    return WorkerSettings(url, None, secret, None, False)


class CallbackTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def preview_env(self):
        os.environ.update({
            'WORKER_DEPLOYMENT_TARGET': 'development',
            'WORKER_EXPECTED_PREVIEW_ORIGIN': PREVIEW,
            'WORKER_VERCEL_OIDC_AUDIENCE': 'https://github.com/russell-algeo',
            'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://oidc.actions.test/token?api-version=2&audience=old',
            'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'github-runtime-test-token',
        })

    def test_production_keeps_existing_header_without_oidc(self):
        os.environ['WORKER_DEPLOYMENT_TARGET'] = 'production'
        with patch('worker.callbacks._open') as request:
            self.assertEqual(callback_headers(settings(secret='production-test-secret')),
                             {'x-internal-secret': 'production-test-secret'})
            request.assert_not_called()

    def test_preview_refuses_missing_secret_without_production_fallback(self):
        self.preview_env()
        with self.assertRaisesRegex(RuntimeError, 'INTERNAL_WORKER_SHARED_SECRET'):
            callback_headers(settings(secret=None))

    def test_preview_refuses_production_or_other_origin_before_minting(self):
        self.preview_env()
        for url in ['https://dj-setlist-generator.vercel.app', PREVIEW + '.evil.test', PREVIEW + '/other']:
            with self.subTest(url=url), patch('worker.callbacks._open') as request:
                with self.assertRaisesRegex(RuntimeError, 'preview origin'):
                    callback_headers(settings(url=url))
                request.assert_not_called()

    def test_preview_requires_explicit_expected_origin_and_oidc(self):
        self.preview_env()
        for key in ['WORKER_EXPECTED_PREVIEW_ORIGIN', 'WORKER_VERCEL_OIDC_AUDIENCE']:
            with self.subTest(key=key), patch.dict(os.environ, {key: ''}):
                with self.assertRaises(RuntimeError):
                    validate_callback_settings(settings())

    def test_preview_cannot_post_to_production_application(self):
        self.preview_env()
        with patch('requests.post') as request, patch('worker.callbacks._open') as oidc:
            with self.assertRaisesRegex(RuntimeError, 'preview origin'):
                post_callback(settings(url='https://dj-setlist-generator.vercel.app'),
                              '/api/internal/finalize-set-run', json={'setRunId': 'test'}, timeout=30)
            request.assert_not_called()
            oidc.assert_not_called()

    def test_oidc_mints_fresh_for_each_callback_and_encodes_audience(self):
        self.preview_env()
        with patch('worker.callbacks._open', side_effect=[io.BytesIO(b'{"value":"first-token"}'), io.BytesIO(b'{"value":"second-token"}')]) as request:
            first = callback_headers(settings())
            second = callback_headers(settings())
        self.assertEqual(first['x-vercel-trusted-oidc-idp-token'], 'first-token')
        self.assertEqual(second['x-vercel-trusted-oidc-idp-token'], 'second-token')
        self.assertEqual(first['x-internal-secret'], 'development-test-secret')
        args = request.call_args_list[0].args[0]
        self.assertEqual(parse_qs(urlsplit(args.full_url).query),
                         {'api-version': ['2'], 'audience': ['https://github.com/russell-algeo']})
        self.assertEqual(args.get_header('Authorization'), 'Bearer github-runtime-test-token')

    def test_oidc_missing_job_permission_fails_closed(self):
        self.preview_env()
        os.environ.pop('ACTIONS_ID_TOKEN_REQUEST_TOKEN')
        with self.assertRaisesRegex(RuntimeError, 'id-token: write'):
            callback_headers(settings())

    def test_oidc_errors_hide_credentials_and_response(self):
        self.preview_env()
        error = HTTPError('https://private.test/secret', 403, 'private-token', {}, None)
        with patch('worker.callbacks._open', side_effect=error):
            with self.assertRaises(RuntimeError) as caught:
                callback_headers(settings())
        self.assertNotIn('private', str(caught.exception))

    def test_invalid_tokens_and_insecure_urls_rejected(self):
        self.preview_env()
        for payload in [{}, {'value': ''}, {'value': 'token\ninjected'}, {'value': 12}]:
            with self.subTest(payload=payload), patch('worker.callbacks._open', return_value=io.BytesIO(json.dumps(payload).encode())):
                with self.assertRaises(RuntimeError):
                    callback_headers(settings())
        os.environ['ACTIONS_ID_TOKEN_REQUEST_URL'] = 'http://insecure.test'
        with self.assertRaisesRegex(RuntimeError, 'HTTPS'):
            callback_headers(settings())

    def test_requests_callbacks_never_follow_redirects(self):
        response = MagicMock(status_code=302)
        with patch('requests.post', return_value=response) as request:
            with self.assertRaisesRegex(RuntimeError, 'redirects'):
                post_callback(settings(), '/api/internal/revalidate', json={'paths': []}, timeout=30)
        self.assertFalse(request.call_args.kwargs['allow_redirects'])
        self.assertEqual(request.call_args.kwargs['json'], {'paths': []})

    def test_cli_posts_payload_without_printing_response_or_credentials(self):
        response = MagicMock(status=200)
        response.__enter__.return_value = response
        with patch('worker.callbacks.get_settings', return_value=settings()), patch('worker.callbacks._open', return_value=response) as request, patch('sys.argv', ['callbacks', '/api/internal/finalize-set-run']), patch('sys.stdin', io.StringIO('{"setRunId":"test-id"}')), patch('sys.stdout', new_callable=io.StringIO) as output:
            main()
            self.assertEqual(output.getvalue(), 'Internal callback completed (HTTP 200)\n')
        req = request.call_args.args[0]
        self.assertEqual(req.full_url, PREVIEW + '/api/internal/finalize-set-run')
        self.assertEqual(json.loads(req.data), {'setRunId': 'test-id'})
        self.assertEqual(req.get_header('X-internal-secret'), 'development-test-secret')
        self.assertIsNone(_NoRedirects().redirect_request(None, None, 302, '', {}, 'https://elsewhere.test'))

    def test_cli_failure_is_nonzero_and_does_not_expose_response(self):
        for path in ['/api/internal/scheduler', '/api/internal/finalize-discovery', '/api/internal/finalize-set-run']:
            with self.subTest(path=path), patch('worker.callbacks.get_settings', return_value=settings()), patch('worker.callbacks._open', side_effect=HTTPError('https://private.test', 503, 'secret-body', {}, None)), patch('sys.argv', ['callbacks', path]), patch('sys.stdin', io.StringIO('{}')):
                with self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(str(error.exception), 'Internal callback failed (HTTP 503)')

    def test_cli_check_performs_no_network_calls(self):
        with patch('worker.callbacks.get_settings', return_value=settings()), patch('worker.callbacks._open') as request, patch('sys.argv', ['callbacks', '--check']):
            main()
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
