import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
import hashlib
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('boka_film', Path(__file__).parents[1] / 'scripts/boka_film.py')
boka = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boka)


def token(seconds=900):
    return {'code': 200, 'data': {'responseMetadata': {'region': 'cn-north-1', 'error': None},
            'result': {'credentials': {'accessKeyId': 'fake-ak', 'secretAccessKey': 'fake-sk',
            'sessionToken': 'fake-token',
            'expiredTime': (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()}}}}


class TosTests(unittest.TestCase):
    def test_token_route_and_redaction(self):
        with patch.object(boka, 'request', return_value=token()) as req, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(boka.main(['get-tos-token']), 0)
        req.assert_called_once_with('GET', boka.TOS_TOKEN_PATH, api_root=boka.API_ORIGIN, sensitive=True)
        self.assertNotIn('fake-', out.getvalue())
        self.assertEqual(json.loads(out.getvalue())['credentials']['sessionToken'], '[REDACTED]')

    def test_invalid_tokens(self):
        for response in (token(-1), token(10), {'code': 200, 'data': {}},
                         {'code': 200, 'data': {'responseMetadata': {'error': {'code': 'Denied'}}}}):
            with self.subTest(response=response), patch.object(boka, 'request', return_value=response):
                with self.assertRaises(boka.ApiError):
                    boka.get_tos_token()

    def test_private_token_file_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'token.json'
            response = token()
            boka.save_token(target, response)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(target.read_text()), response)
            with self.assertRaises(FileExistsError):
                boka.save_token(target, {})

    def test_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'test.jpg'
            file.write_bytes(b'fake-image')
            with patch.object(boka, 'get_tos_token') as get, redirect_stdout(io.StringIO()) as out:
                boka.upload_file(file, 'Pic/参考 图.jpg', True)
            get.assert_not_called()
            result = json.loads(out.getvalue())
            self.assertEqual(result['url'], 'https://god-chat.tos-cn-beijing.volces.com/Pic/%E5%8F%82%E8%80%83%20%E5%9B%BE.jpg')
            self.assertTrue(result['dry_run'])
            self.assertEqual(result['content_type'], 'image/jpeg')

    def test_upload_sends_signed_stream_without_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'test.png'
            file.write_bytes(b'fake-image')
            captured = {}
            class Response:
                headers = {'ETag': 'etag', 'x-tos-request-id': 'request'}
                def __enter__(self): return self
                def __exit__(self, *args): pass
            def send(req, timeout):
                captured['request'] = req
                captured['body'] = req.data.read()
                return Response()
            opener = Mock()
            opener.open.side_effect = send
            with patch.object(boka, 'build_opener', return_value=opener), patch.object(boka, 'request', return_value=token()), redirect_stdout(io.StringIO()) as out:
                boka.upload_file(file, 'Pic/测试.png')
            req = captured['request']
            self.assertEqual(req.method, 'PUT')
            self.assertEqual(captured['body'], b'fake-image')
            self.assertEqual(req.get_header('Content-length'), '10')
            self.assertEqual(req.get_header('X-tos-content-sha256'), hashlib.sha256(b'fake-image').hexdigest())
            self.assertEqual(req.get_header('X-tos-security-token'), 'fake-token')
            self.assertEqual(req.get_header('X-tos-forbid-overwrite'), 'true')
            self.assertTrue(req.get_header('Authorization').startswith('TOS4-HMAC-SHA256 '))
            self.assertNotIn('fake-', out.getvalue())
            self.assertEqual(json.loads(out.getvalue())['etag'], 'etag')
            opener.open.assert_called_once()

    def test_http_failure_is_redacted_and_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'test.jpg'
            file.write_bytes(b'fake')
            opener = Mock()
            opener.open.side_effect = HTTPError('https://example.com', 403, 'fake-token fake-sk', {}, None)
            with patch.object(boka, 'build_opener', return_value=opener), patch.object(boka, 'request', return_value=token()), redirect_stderr(io.StringIO()) as err:
                self.assertEqual(boka.main(['upload', '--file', str(file)]), 1)
            self.assertNotIn('fake-', err.getvalue())
            self.assertIn('403', err.getvalue())
            opener.open.assert_called_once()

    def test_existing_project_route(self):
        with patch.object(boka, 'request', return_value={'code': 200}) as req, redirect_stdout(io.StringIO()):
            self.assertEqual(boka.main(['create-project', '--name', '电影']), 0)
        req.assert_called_once_with('POST', '/create', {'name': '电影'})


if __name__ == '__main__':
    unittest.main()
