# TOS 临时凭证与素材上传

## 获取凭证

```text
GET https://api.bonanai.com/api/bkk/task/getBonaHmccOssToken
Authorization: Bearer <BOKA_API_KEY>
clientid: 98e4e8de3d6b43a79ad466354474d6d0
```

此接口不在 `/api/film/v1/film` 下。认证与博卡 API 相同，不携带请求体。

响应结构（密钥已替换为示意值）：

```json
{
  "code": 200,
  "msg": "获取临时token成功",
  "data": {
    "responseMetadata": {"service": "sts", "region": "cn-north-1", "error": null},
    "result": {
      "credentials": {
        "currentTime": "2026-09-08T10:57:09+08:00",
        "expiredTime": "2026-09-08T11:12:09+08:00",
        "accessKeyId": "<temporary-access-key-id>",
        "secretAccessKey": "<temporary-secret-access-key>",
        "sessionToken": "<temporary-session-token>"
      }
    }
  }
}
```

凭证位于 `data.result.credentials`，不是 `data.credentials`。以 `expiredTime` 为准，不把示例的 15 分钟当作固定有效期。上传前重新获取，脚本拒绝已过期或剩余不足 30 秒的凭证。STS 的区域字段不代表 bucket 的区域。

```bash
python3 scripts/boka_film.py get-tos-token
python3 scripts/boka_film.py get-tos-token --output .tos-token.json
```

默认仅输出时间和脱敏密钥字段。`--output` 将完整响应保存为权限 `0600` 的新文件；不覆盖已有文件。该文件包含临时密钥，不加入版本控制，不在对话里展示；使用完后删除。

## 上传素材

从用户给出的对象地址可确定：

| 配置 | 值 |
| --- | --- |
| Bucket | `god-chat` |
| Endpoint | `https://tos-cn-beijing.volces.com` |
| TOS region | `cn-beijing` |
| URL 域名 | `https://god-chat.tos-cn-beijing.volces.com` |
| 默认对象前缀 | `Pic/` |

可为上传命令单独创建 Python 虚拟环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-upload.txt
.venv/bin/python scripts/boka_film.py upload --file /absolute/path/reference.jpg --dry-run
.venv/bin/python scripts/boka_film.py upload --file /absolute/path/reference.jpg
.venv/bin/python scripts/boka_film.py upload --file /absolute/path/reference.mp4 --key 'Pic/reference-video.mp4'
```

`--dry-run` 只预览对象 key、URL、类型和大小，不获取凭证、不上传，也不需要 SDK。默认 key 为 `Pic/毫秒时间戳_UUID.扩展名`；每次调用都会生成新的 key。需要固定预览和实际上传目标时显式传入相同 `--key`。

显式 key 使用原始路径（如 `Pic/参考 图.jpg`），不是 URL，不预先转义 `/` 或空格。输出 URL 统一编码特殊字符，保留路径斜杠。用户示例 URL 中的 `Pic%2F文件名.jpg` 对应对象 key `Pic/文件名.jpg`。

上传采用官方 `tos.TosClientV2`，将 `accessKeyId`、`secretAccessKey`、`sessionToken` 分别传给 AK、SK 和 `security_token`。通过 `put_object_from_file` 读取本地文件，自动识别 Content-Type，禁止覆盖同名对象，不自动重试，不修改 bucket 或对象 ACL。博卡 Bearer 只发送到凭证接口，TOS 上传由 SDK 单独签名。

成功输出 `bucket`、`region`、`key`、`url`、`content_type`、`size`、`etag` 和 `request_id`，不输出临时凭证。返回的对象 URL 可填入生成请求的 `image_url`、`video_url`、`audio_url` 或首尾帧字段。能否匿名读取仍取决于该 bucket 的现有权限；上传成功并不证明匿名读取成功。

当前使用单次普通上传，未实现分片续传。上传中凭证到期、断网或对象重名时退出失败；先核查对象状态，再决定是否用新 key 重传。

官方依据：[Python 普通上传](https://www.volcengine.com/docs/6349/92800?lang=zh)、[TOS SDK 源码](https://github.com/volcengine/ve-tos-python-sdk/blob/master/tos/clientv2.py)。
