#!/usr/bin/env python3
"""博卡电影云片场 API CLI; Python 3.9+, standard library only, including signed TOS uploads."""
import argparse
import json
import mimetypes
import math
import hashlib
import hmac
import uuid
from datetime import datetime, timezone
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = 'https://api.bonanai.com/api/film/v1/film'
API_ORIGIN = 'https://api.bonanai.com'
TOS_TOKEN_PATH = '/api/bkk/task/getBonaHmccOssToken'
TOS_BUCKET = 'god-chat'
TOS_ENDPOINT = 'https://tos-cn-beijing.volces.com'
TOS_REGION = 'cn-beijing'
CLIENT_ID = '98e4e8de3d6b43a79ad466354474d6d0'

class ApiError(Exception):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(method, path, payload=None, timeout=30, *, api_root=BASE, sensitive=False):
    key = os.environ.get('BOKA_API_KEY', '').strip()
    if not key or key == 'sk-bk-xxxxxxxx':
        raise ApiError('请设置环境变量 BOKA_API_KEY 为真实 API Key')
    headers = {'Authorization': 'Bearer ' + key, 'clientid': CLIENT_ID,
               'Accept': 'application/json', 'Content-Type': 'application/json;charset=UTF-8'}
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = Request(api_root + path, data=body, headers=headers, method=method)
    try:
        with build_opener(NoRedirect()).open(req, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise ApiError(f'HTTP {exc.code}；请检查认证、参数和服务状态。提交请求不会自动重试。') from None
    except (URLError, TimeoutError, OSError) as exc:
        raise ApiError('网络请求失败或超时；提交结果可能不确定，请核查平台项目或任务，勿重复提交。') from None
    except (ValueError, UnicodeError):
        raise ApiError('服务未返回有效 JSON') from None
    if not isinstance(result, dict) or str(result.get('code')) != '200':
        if sensitive:
            raise ApiError('获取临时凭证业务失败；响应内容已隐藏')
        raise ApiError('API 业务失败：' + json.dumps(result, ensure_ascii=False).replace(key, '[REDACTED]'))
    return result


def get_tos_token():
    result = request('GET', TOS_TOKEN_PATH, api_root=API_ORIGIN, sensitive=True)
    try:
        data = result['data']
        if data.get('responseMetadata', {}).get('error'):
            raise ApiError('STS 返回错误；临时凭证不可用')
        credentials = data['result']['credentials']
        for key in ('accessKeyId', 'secretAccessKey', 'sessionToken', 'expiredTime'):
            if not isinstance(credentials.get(key), str) or not credentials[key]:
                raise ValueError()
        expires = datetime.fromisoformat(credentials['expiredTime'].replace('Z', '+00:00'))
        if expires.tzinfo is None:
            raise ValueError()
        if (expires - datetime.now(timezone.utc)).total_seconds() <= 30:
            raise ApiError('TOS 临时凭证已过期或即将过期，请重新获取')
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ApiError('TOS 响应缺少有效临时凭证或过期时间') from None
    return result, credentials


def token_summary(credentials):
    return {key: ('[REDACTED]' if key in ('accessKeyId', 'secretAccessKey', 'sessionToken') else value)
            for key, value in credentials.items()
            if key in ('accessKeyId', 'secretAccessKey', 'sessionToken', 'currentTime', 'expiredTime')}


def save_token(path, result):
    # Exclusive creation avoids replacing existing files or following symlinks.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def tos_signed_headers(key, credentials, content_type, payload_hash, timestamp=None):
    """Sign a query-free PUT using TOS4-HMAC-SHA256 (raw SK, no AWS4 prefix)."""
    date = timestamp or datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    host = f'{TOS_BUCKET}.{urlparse(TOS_ENDPOINT).netloc}'
    headers = {'host': host, 'content-type': content_type,
               'x-tos-date': date, 'x-tos-content-sha256': payload_hash,
               'x-tos-security-token': credentials['sessionToken'],
               'x-tos-forbid-overwrite': 'true'}
    names = sorted(headers)
    signed_names = ';'.join(names)
    canonical_headers = ''.join(f'{name}:{headers[name]}\n' for name in names)
    canonical_request = '\n'.join(('PUT', quote('/' + key, safe='/~'), '',
                                   canonical_headers, signed_names, payload_hash))
    scope = f'{date[:8]}/{TOS_REGION}/tos/request'
    string_to_sign = '\n'.join(('TOS4-HMAC-SHA256', date, scope,
                               hashlib.sha256(canonical_request.encode()).hexdigest()))
    signing_key = credentials['secretAccessKey'].encode()
    for value in (date[:8], TOS_REGION, 'tos', 'request'):
        signing_key = hmac.new(signing_key, value.encode(), hashlib.sha256).digest()
    signature = hmac.new(signing_key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    headers['Authorization'] = (f'TOS4-HMAC-SHA256 Credential={credentials["accessKeyId"]}/{scope}, '
                                f'SignedHeaders={signed_names}, Signature={signature}')
    return headers


def upload_file(file_path, object_key=None, dry_run=False):
    file_path = file_path.expanduser().resolve()
    if not file_path.is_file():
        raise ApiError('待上传文件不存在或不是普通文件')
    key = object_key if object_key is not None else (
        f'Pic/{int(time.time() * 1000)}_{uuid.uuid4().hex}{file_path.suffix.lower()}')
    if not key or key.startswith('/') or any(part in ('.', '..') for part in key.split('/')):
        raise ApiError('对象 key 必须非空、不能以 / 开头或包含 .、.. 路径段')
    content_type = mimetypes.guess_type(file_path.name)[0] or 'application/octet-stream'
    url = f'https://{TOS_BUCKET}.tos-cn-beijing.volces.com/{quote(key, safe="/")}'
    output = {'bucket': TOS_BUCKET, 'region': TOS_REGION, 'key': key,
              'url': url, 'content_type': content_type, 'size': file_path.stat().st_size}
    if dry_run:
        emit(dict(output, dry_run=True))
        return
    try:
        with file_path.open('rb') as stream:
            # Hash and send in chunks so large media are not loaded into memory.
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
                size += len(chunk)
            stream.seek(0)
            _, credentials = get_tos_token()
            headers = tos_signed_headers(key, credentials, content_type, digest.hexdigest())
            headers['Content-Length'] = str(size)
            req = Request(url, data=stream, headers=headers, method='PUT')
            with build_opener(NoRedirect()).open(req, timeout=60) as response:
                output.update(size=size, etag=response.headers.get('ETag'),
                              request_id=response.headers.get('x-tos-request-id'))
    except HTTPError as exc:
        raise ApiError(f'TOS 上传 HTTP {exc.code}；未自动重试。请检查凭证权限、签名及对象是否已存在：{key}') from None
    except (URLError, TimeoutError, OSError):
        raise ApiError(f'TOS 上传失败或结果不确定；未自动重试，请核查对象：{key}') from None
    emit(output)


def validate_payload(kind, payload):
    if not isinstance(payload, dict):
        raise ApiError('请求 JSON 必须是对象')
    for field in ('model_name', 'model_version', 'project_id', 'aspect_ratio', 'resolution'):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ApiError(f'{field} 必须是非空字符串；项目 ID 应以字符串传入')
    if not isinstance(payload.get('prompt'), str):
        raise ApiError('prompt 必须是字符串（首尾帧示例允许空字符串）')
    for field in ('image_url', 'video_url', 'audio_url'):
        if field in payload:
            values = payload[field]
            if not isinstance(values, list) or any(not isinstance(v, str) or urlparse(v).scheme not in ('https', 'http') or not urlparse(v).netloc for v in values):
                raise ApiError(f'{field} 必须是 HTTP(S) URL 数组')
    for field in ('first_frame_url', 'last_frame_url'):
        if payload.get(field) and (not isinstance(payload[field], str) or urlparse(payload[field]).scheme not in ('https', 'http') or not urlparse(payload[field]).netloc):
            raise ApiError(f'{field} 必须是 HTTP(S) URL')
    if kind == 'video':
        duration = payload.get('durations')
        if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
            raise ApiError('durations 必须是正整数，具体范围以模型为准')
        if payload.get('last_frame_url') and not payload.get('first_frame_url'):
            raise ApiError('设置尾帧时须提供首帧')


def emit(result):
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


def task_path(task_id):
    return '/task/' + quote(task_id, safe='')


def wait_task(task_id, interval, max_wait):
    deadline = time.monotonic() + max_wait
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ApiError(f'等待超时，任务并未取消。请使用 query --task-id {task_id} 继续查询')
        result = request('GET', task_path(task_id), timeout=min(30, remaining))
        data = result.get('data')
        if not isinstance(data, dict):
            raise ApiError('任务响应缺少 data 对象')
        status = str(data.get('status'))
        if status == '9':
            emit(result)
            return 0
        if status == '-1':
            emit(result)
            return 1
        print(f'任务 {task_id} 状态：{status}', file=sys.stderr, flush=True)
        # null and undocumented statuses are not assumed to mean success/failure.
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(interval, remaining))


def project_tasks_path(project_id):
    if not project_id.strip() or project_id in ('.', '..'):
        raise ApiError('project_id 必须为有效的非空字符串')
    return '/resource/generated/list/' + quote(project_id, safe='')


def validate_canvas_resources(resources):
    if not isinstance(resources, list) or not resources:
        raise ApiError('画布请求体必须是非空资源数组')
    seen = set()
    for resource in resources:
        if not isinstance(resource, dict):
            raise ApiError('画布资源必须是对象')
        node_id = resource.get('id')
        if not isinstance(node_id, str) or not node_id.strip() or node_id in seen:
            raise ApiError('资源 id 必须是非空且批次内不重复的节点 ID')
        seen.add(node_id)
        if not isinstance(resource.get('canvas'), str) or not resource['canvas'].strip():
            raise ApiError('每个资源必须指定非空 canvas 画布名称')
        node = resource.get('webLocation')
        if not isinstance(node, dict) or node.get('id') != node_id:
            raise ApiError('webLocation 必须是节点对象，且 id 与外层资源 id 一致')
        kind = node.get('type')
        if kind not in ('image', 'video'):
            raise ApiError('保存命令支持 image 或 video 媒体节点')
        position = node.get('position')
        if not isinstance(position, dict) or any(
            isinstance(position.get(axis), bool) or not isinstance(position.get(axis), (int, float))
            or not math.isfinite(position[axis]) for axis in ('x', 'y')
        ):
            raise ApiError('节点 position.x/y 必须是有限数字')
        data = node.get('data')
        if not isinstance(data, dict) or not isinstance(data.get('taskId'), str):
            raise ApiError('节点 data 必须含字符串 taskId；仅上传素材可填空字符串')
        url = data.get('imageUrl' if kind == 'image' else 'videoUrl')
        if not isinstance(url, str) or urlparse(url).scheme not in ('http', 'https') or not urlparse(url).netloc:
            raise ApiError('节点必须提供对应的 HTTP(S) imageUrl 或 videoUrl')
        for dimension in ('width', 'height'):
            if dimension in data and (isinstance(data[dimension], bool)
                or not isinstance(data[dimension], (int, float))
                or not math.isfinite(data[dimension]) or data[dimension] <= 0):
                raise ApiError('节点 width/height 必须是正的有限数字')


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('必须大于 0')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    token = commands.add_parser('get-tos-token', help='获取临时凭证，默认输出脱敏摘要')
    token.add_argument('--output', type=Path, help='将完整响应保存为权限 0600 的新文件')
    upload = commands.add_parser('upload', help='上传本地素材到 god-chat bucket')
    upload.add_argument('--file', type=Path, required=True)
    upload.add_argument('--key', help='原始对象 key，不做预先 URL 编码；默认 Pic/ 下唯一文件名')
    upload.add_argument('--dry-run', action='store_true', help='预览上传目标，不获取凭证或上传')
    models = commands.add_parser('models', help='查询可用模型及能力')
    models.add_argument('--kind', choices=('image', 'video'), required=True)
    project = commands.add_parser('create-project', help='创建云端项目，只提交一次')
    project.add_argument('--name', required=True, help='项目名称；可显式传入空字符串')
    project.add_argument('--dry-run', action='store_true', help='仅输出请求体，不请求 API')
    for kind in ('image', 'video'):
        create = commands.add_parser('create-' + kind, help='提交生成任务，默认只提交一次')
        create.add_argument('--payload', type=Path, required=True, help='请求 JSON 文件')
        create.add_argument('--dry-run', action='store_true', help='仅校验并输出请求体，不请求 API')
    tasks = commands.add_parser('list-tasks', help='查询项目下所有生成任务')
    tasks.add_argument('--project-id', required=True, help='项目 ID（字符串）')
    tasks.add_argument('--dry-run', action='store_true', help='预览 POST 地址，不发送请求')
    for action in ('canvas-list', 'canvas-resources', 'save-canvas'):
        canvas = commands.add_parser(action, help={'canvas-list': '列出项目已有画布',
            'canvas-resources': '查询项目画布资源', 'save-canvas': '批量保存图片或视频节点到画布'}[action])
        canvas.add_argument('--project-id', required=True)
        canvas.add_argument('--dry-run', action='store_true', help='仅预览请求，不调用 API')
        if action == 'save-canvas':
            canvas.add_argument('--payload', type=Path, required=True, help='资源数组 JSON 文件')
    query = commands.add_parser('query', help='查询已有任务')
    query.add_argument('--task-id', required=True)
    wait = commands.add_parser('wait', help='有界轮询已有任务')
    wait.add_argument('--task-id', required=True)
    wait.add_argument('--interval', type=positive, default=10)
    wait.add_argument('--max-wait', type=positive, default=1200)
    args = parser.parse_args(argv)
    try:
        if args.command == 'get-tos-token':
            result, credentials = get_tos_token()
            if args.output:
                save_token(args.output, result)
            emit({'credentials': token_summary(credentials),
                  'output': str(args.output) if args.output else None})
        elif args.command == 'upload':
            upload_file(args.file, args.key, args.dry_run)
        elif args.command == 'models':
            emit(request('GET', '/models/' + args.kind))
        elif args.command == 'create-project':
            payload = {'name': args.name}
            if args.dry_run:
                emit({'method': 'POST', 'url': BASE + '/create', 'payload': payload})
            else:
                emit(request('POST', '/create', payload))
        elif args.command.startswith('create-'):
            kind = args.command.removeprefix('create-')
            payload = json.loads(args.payload.read_text(encoding='utf-8'))
            validate_payload(kind, payload)
            if args.dry_run:
                emit({'method': 'POST', 'url': BASE + '/' + kind, 'payload': payload})
            else:
                emit(request('POST', '/' + kind, payload))
        elif args.command == 'list-tasks':
            path = project_tasks_path(args.project_id)
            if args.dry_run:
                emit({'method': 'POST', 'url': BASE + path, 'payload': None})
            else:
                emit(request('POST', path))
        elif args.command in ('canvas-list', 'canvas-resources', 'save-canvas'):
            project_id = project_tasks_path(args.project_id).rsplit('/', 1)[-1]
            prefix = {'canvas-list': '/resource/canvas/list/',
                      'canvas-resources': '/resource/list/',
                      'save-canvas': '/resource/save/batch/'}[args.command]
            path = prefix + project_id
            payload = None
            if args.command == 'save-canvas':
                payload = json.loads(args.payload.read_text(encoding='utf-8'))
                validate_canvas_resources(payload)
            if args.dry_run:
                emit({'method': 'POST', 'url': BASE + path, 'payload': payload})
            else:
                emit(request('POST', path, payload))
        elif args.command == 'query':
            emit(request('GET', task_path(args.task_id)))
        else:
            return wait_task(args.task_id, args.interval, args.max_wait)
        return 0
    except (ApiError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('已停止本地等待；远端任务未取消。', file=sys.stderr)
        return 130

if __name__ == '__main__':
    sys.exit(main())
