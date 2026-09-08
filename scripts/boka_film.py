#!/usr/bin/env python3
"""博卡电影云片场 API CLI; Python 3.9+, standard library only."""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = 'https://api.bonanai.com/api/film/v1/film'
CLIENT_ID = '98e4e8de3d6b43a79ad466354474d6d0'

class ApiError(Exception):
    pass

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(method, path, payload=None, timeout=30):
    key = os.environ.get('BOKA_API_KEY', '').strip()
    if not key or key == 'sk-bk-xxxxxxxx':
        raise ApiError('请设置环境变量 BOKA_API_KEY 为真实 API Key')
    headers = {'Authorization': 'Bearer ' + key, 'clientid': CLIENT_ID,
               'Accept': 'application/json', 'Content-Type': 'application/json;charset=UTF-8'}
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = Request(BASE + path, data=body, headers=headers, method=method)
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
        raise ApiError('API 业务失败：' + json.dumps(result, ensure_ascii=False).replace(key, '[REDACTED]'))
    return result


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


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('必须大于 0')
    return number


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    models = commands.add_parser('models', help='查询可用模型及能力')
    models.add_argument('--kind', choices=('image', 'video'), required=True)
    project = commands.add_parser('create-project', help='创建云端项目，只提交一次')
    project.add_argument('--name', required=True, help='项目名称；可显式传入空字符串')
    project.add_argument('--dry-run', action='store_true', help='仅输出请求体，不请求 API')
    for kind in ('image', 'video'):
        create = commands.add_parser('create-' + kind, help='提交生成任务，默认只提交一次')
        create.add_argument('--payload', type=Path, required=True, help='请求 JSON 文件')
        create.add_argument('--dry-run', action='store_true', help='仅校验并输出请求体，不请求 API')
    query = commands.add_parser('query', help='查询已有任务')
    query.add_argument('--task-id', required=True)
    wait = commands.add_parser('wait', help='有界轮询已有任务')
    wait.add_argument('--task-id', required=True)
    wait.add_argument('--interval', type=positive, default=10)
    wait.add_argument('--max-wait', type=positive, default=1200)
    args = parser.parse_args(argv)
    try:
        if args.command == 'models':
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
