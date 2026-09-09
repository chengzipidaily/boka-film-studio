# 博卡电影云片场 API

依据用户提供的接口说明整理。基础地址：`https://api.bonanai.com/api/film/v1/film`。

所有请求携带：

```text
Authorization: Bearer <BOKA_API_KEY>
clientid: 98e4e8de3d6b43a79ad466354474d6d0
Accept: application/json
Content-Type: application/json;charset=UTF-8
```

浏览器抓包里的 Cookie、User-Agent、sec-* 等字段不需要复制。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/models/image` | 图片模型列表 |
| GET | `/models/video` | 视频模型列表 |
| POST | `/create` | 创建云端项目 |
| POST | `/image` | 创建图片任务 |
| POST | `/video` | 创建视频任务 |
| GET | `/task/{task_id}` | 查询图片或视频任务 |
| POST | `/resource/generated/list/{project_id}` | 查询项目下全部生成任务 |

另有独立路径 `GET https://api.bonanai.com/api/bkk/task/getBonaHmccOssToken`，不使用上述 film 基础路径。认证相同，响应与上传方式见 [tos.md](tos.md)。

## 查询项目下所有生成任务

线上接口（与其他 film 接口统一走 API 网关）：

```bash
curl -X POST 'https://api.bonanai.com/api/film/v1/film/resource/generated/list/123'
```

`123` 为项目 ID，路径参数按字符串处理。方法为 **POST**，示例无请求体。使用与其他 film 接口相同的基础地址，追加 `/resource/generated/list/{project_id}`。

```bash
python3 scripts/boka_film.py list-tasks --project-id 123
python3 scripts/boka_film.py list-tasks --project-id 123 --dry-run
```

默认地址为 `https://api.bonanai.com/api/film/v1/film/resource/generated/list/{project_id}`，无需指定服务地址。

沿用先前全局认证要求：`BOKA_API_KEY` 的 Bearer 认证与固定 `clientid`。精简 curl 未展示请求头，不据此取消认证；`--dry-run` 无需密钥。

响应示例尚未提供，当前沿用现有 API 的 `code: 200` 成功封装并完整输出响应，不假定任务列表字段、不汇总或截断结果。分页、筛选参数尚未提供，不自动添加页码或请求体。若实际响应显示分页，则需要补充分页协议后才能确认取全。

## 画布资源

保存与查询画布使用同一线上 API 基础地址，接口、节点结构及完整流程见 [canvas.md](canvas.md)。

## 创建云端项目

`POST /create`，请求体：

```json
{"name":"春日短片"}
```

`name` 为字符串。用户提供的请求示例为 `{"name":""}`，CLI 保留显式空字符串，不自行补名；空名称的服务端行为尚未验证。

```bash
python3 scripts/boka_film.py create-project --name "春日短片"
python3 scripts/boka_film.py create-project --name "" --dry-run
```

复用相同认证头。根据前端 `src/types/project.ts` 的 `ProjectInfo`，创建项目返回对象含 `id`；原始 API 成功封装中读取 `data.id`。CLI 原样输出响应，不自动串联生成任务。确认实际返回的项目 ID 后，以字符串填入图片或视频请求的 `project_id`。创建请求不自动重试。

## 生成请求体

以下模型及参数来自提供的示例，使用前查询模型列表确认。将 `YOUR_PROJECT_ID` 和素材 URL 替换为用户的实际值。字段的完整必填约束、模型列表响应结构、素材数量上限未提供；脚本进行基础校验，实际能力以服务端为准。

### 图片

```json
{
  "model_name": "GEM",
  "model_version": "3.1",
  "prompt": "踏青，春日自然光，电影感构图",
  "image_url": ["https://example.com/reference.png"],
  "aspect_ratio": "adaptive",
  "resolution": "1K",
  "project_id": "YOUR_PROJECT_ID"
}
```

`image_url` 为参考图数组。无参考素材时可尝试空数组，是否支持纯文本生成须确认模型能力。

### 视频：参考模式

```json
{
  "model_name": "seedance-2",
  "model_version": "doubao-seedance-2-5-260628",
  "prompt": "人物在春日草地上行走，镜头缓慢跟随",
  "image_url": ["https://example.com/reference.png"],
  "aspect_ratio": "21:9",
  "resolution": "1080p",
  "durations": 7,
  "video_url": [],
  "audio_url": ["https://example.com/reference.mp3"],
  "project_id": "YOUR_PROJECT_ID"
}
```

时长字段是 `durations`，单位秒。参考图片、视频、音频分别使用 URL 数组；未使用的参考类别可为空数组，支持情况以模型为准。

### 视频：首尾帧模式

```json
{
  "model_name": "Kling",
  "model_version": "3.0",
  "prompt": "",
  "image_url": [],
  "aspect_ratio": "21:9",
  "resolution": "720P",
  "durations": 7,
  "first_frame_url": "https://example.com/first.png",
  "last_frame_url": "",
  "project_id": "YOUR_PROJECT_ID"
}
```

示例允许空提示词与空尾帧。首尾帧使用独立字段，不放入参考图数组。不添加未经说明的 `mode` 字段。

## 响应与轮询

创建图片任务的示例（视频创建响应未单独给出，实际返回时检查 `data.id`）：

```json
{"code":200,"msg":"success","data":{"id":"img_1788833180851672518","status":null,"error_code":null,"error_message":null}}
```

任务查询：

```json
{"code":200,"msg":"success","data":{"status":1,"error_code":null,"error_message":null}}
```

| status | 含义 |
| --- | --- |
| 1 | 进行中 |
| -1 | 失败，读取 error_code/error_message |
| 9 | 成功，读取 result_url 数组 |

成功示例：

```json
{"code":200,"msg":"success","data":{"status":9,"error_code":null,"error_message":null,"result_url":["https://example.com/result.png"]}}
```

素材上传使用 [TOS 临时凭证和上传流程](tos.md)。未提供任务取消、云端项目列表、更新或删除接口；不要自行拼接这些接口。无需重新创建任务来查询结果。
