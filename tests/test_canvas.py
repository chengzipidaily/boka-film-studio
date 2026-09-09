import copy
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('boka_canvas', Path(__file__).parents[1] / 'scripts/boka_film.py')
boka = importlib.util.module_from_spec(spec)
spec.loader.exec_module(boka)


def resource(kind='image'):
    return {'id': 'node-1', 'canvas': '画布1', 'webLocation': {
        'id': 'node-1', 'type': kind, 'position': {'x': 240, 'y': 120},
        'data': {'taskId': 'task-1', 'imageUrl' if kind == 'image' else 'videoUrl': 'https://example.com/media'}}}


class CanvasTests(unittest.TestCase):
    def invoke_save(self, resources, *options):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'canvas.json'
            p.write_text(json.dumps(resources))
            return boka.main(['save-canvas', '--project-id', '123', '--payload', str(p), *options])

    def test_save_sends_exact_array_once(self):
        resources = [resource()]
        reply = {'code': 200, 'data': resources}
        with patch.object(boka, 'request', return_value=reply) as request, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.invoke_save(resources), 0)
        request.assert_called_once_with('POST', '/resource/save/batch/123', resources)
        self.assertEqual(json.loads(out.getvalue()), reply)

    def test_preview_has_no_requests(self):
        resources = [resource('video')]
        with patch.object(boka, 'request') as request, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.invoke_save(resources, '--dry-run'), 0)
        request.assert_not_called()
        self.assertEqual(json.loads(out.getvalue()), {'method': 'POST',
            'url': boka.BASE + '/resource/save/batch/123', 'payload': resources})

    def test_read_routes_use_production_base_and_no_body(self):
        for command, path in [('canvas-list', '/resource/canvas/list/123'),
                              ('canvas-resources', '/resource/list/123')]:
            with self.subTest(command=command), patch.object(boka, 'request', return_value={'code': 200}) as req, redirect_stdout(io.StringIO()):
                self.assertEqual(boka.main([command, '--project-id', '123']), 0)
                req.assert_called_once_with('POST', path, None)

    def test_invalid_nodes_never_send(self):
        cases = [[], {'resources': [resource()]}, [resource(), resource()]]
        for path, value in [(('id',), ''), (('canvas',), ''), (('webLocation',), '{}'),
                            (('webLocation', 'id'), 'different'), (('webLocation', 'type'), 'edge'),
                            (('webLocation', 'position', 'x'), float('nan')),
                            (('webLocation', 'data', 'taskId'), 123),
                            (('webLocation', 'data', 'imageUrl'), '/local.png'),
                            (('webLocation', 'data', 'width'), -1)]:
            r = resource(); target = r
            for key in path[:-1]: target = target[key]
            target[path[-1]] = value
            cases.append([r])
        for resources in cases:
            with self.subTest(resources=resources), patch.object(boka, 'request') as req, redirect_stderr(io.StringIO()):
                self.assertEqual(self.invoke_save(resources), 1)
                req.assert_not_called()

    def test_uploaded_media_and_optional_data_are_preserved(self):
        r = resource()
        r['webLocation']['data'].update(taskId='', width=1024, height=1024, imageSizeResolved=False,
                                      reeditDraft={'prompt': 'preserve'})
        before = copy.deepcopy(r)
        boka.validate_canvas_resources([r])
        self.assertEqual(r, before)


if __name__ == '__main__':
    unittest.main()
