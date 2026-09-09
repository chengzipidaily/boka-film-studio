import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('boka_film', Path(__file__).parents[1] / 'scripts/boka_film.py')
boka = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boka)


class ProjectTasksTests(unittest.TestCase):
    def test_default_preview_needs_no_key_or_request(self):
        with patch.object(boka, 'request') as req, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(boka.main(['list-tasks', '--project-id', '123', '--dry-run']), 0)
        req.assert_not_called()
        self.assertEqual(json.loads(out.getvalue()), {
            'method': 'POST', 'url': 'https://api.bonanai.com/api/film/v1/film/resource/generated/list/123', 'payload': None})

    def test_shared_api_route_and_response_preserved(self):
        response = {'code': 200, 'data': {'arbitrary_list_field': [{'id': 'task-a'}, {'id': 'task-b'}]}}
        with patch.object(boka, 'request', return_value=response) as req, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(boka.main(['list-tasks', '--project-id', '907248981847825121']), 0)
        req.assert_called_once_with('POST', '/resource/generated/list/907248981847825121')
        self.assertEqual(json.loads(out.getvalue()), response)

    def test_transport_post_without_json_body_and_with_auth(self):
        response = io.BytesIO(b'{"code":200,"data":[]}')
        opener = Mock()
        opener.open.return_value = response
        with patch.object(boka, 'build_opener', return_value=opener), \
                patch.dict(boka.os.environ, {'BOKA_API_KEY': 'test-key'}), redirect_stdout(io.StringIO()):
            self.assertEqual(boka.main(['list-tasks', '--project-id', '123']), 0)
        req = opener.open.call_args.args[0]
        self.assertEqual(req.method, 'POST')
        self.assertEqual(req.full_url, 'https://api.bonanai.com/api/film/v1/film/resource/generated/list/123')
        self.assertIsNone(req.data)
        self.assertEqual(req.get_header('Authorization'), 'Bearer test-key')
        self.assertEqual(req.get_header('Clientid'), boka.CLIENT_ID)

    def test_project_id_is_encoded_as_single_path_segment(self):
        self.assertEqual(boka.project_tasks_path('a/b?x=1'), '/resource/generated/list/a%2Fb%3Fx%3D1')
        for value in ('', ' ', '.', '..'):
            with self.assertRaises(boka.ApiError):
                boka.project_tasks_path(value)


if __name__ == '__main__':
    unittest.main()
