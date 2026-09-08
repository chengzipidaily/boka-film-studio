---
name: boka-film-studio
description: 使用博卡电影云片场 API 创建云端项目、查询模型、生成图片和视频、查询及等待生成任务。适用于用户要求通过博卡或 Boka 创建云端项目、制作图片、参考素材视频或首尾帧视频；仅编写提示词时不调用 API。
---

# 博卡电影云片场

通过随附 `scripts/boka_film.py` 调用博卡 API。需要 Python 3.9+，仅依赖标准库。

## 配置

从环境变量 `BOKA_API_KEY` 读取用户配置的 API Key。缺失时请用户配置；不把密钥写入脚本、请求 JSON、文档或输出。脚本不会自动读取 `.env`。
所有 API 请求发送 Bearer 认证和固定 `clientid: 98e4e8de3d6b43a79ad466354474d6d0`。

## 工作流程

1. 按需阅读 [references/api.md](references/api.md)，选择图片、参考视频或首尾帧视频请求结构。
2. 使用 `models --kind image` 或 `models --kind video` 获取当前模型及能力，以响应为准选择版本、分辨率、比例和时长，保留大小写。示例不是当前能力清单。
3. 复用用户指定的 `project_id`（字符串）；需要新建云端项目时使用 `create-project --name "项目名称"`。创建接口的响应结构尚未提供，检查实际响应以识别项目 ID，再用于生成请求；无法识别时请用户补充响应说明，不猜测字段或使用示例 ID。
4. 将请求体保存为 JSON，运行 `create-image` 或 `create-video`。可先加 `--dry-run` 验证请求。用户已要求生成时直接提交；仅准备方案或提示词不提交。
5. 记录返回的 `data.id`，用 `query` 或 `wait` 查询。提交响应不代表生成完成；只有状态 `9` 表示成功。
6. 返回任务 ID、状态及成功响应中的 `result_url` 链接。失败时报告 `error_code`/`error_message`。轮询超时保留任务 ID，后续继续查原任务。

命令中的脚本路径相对于本 Skill 目录；实际执行时使用该目录下的绝对路径。

```bash
python3 scripts/boka_film.py create-project --name "春日短片" --dry-run
python3 scripts/boka_film.py create-project --name "春日短片"
python3 scripts/boka_film.py models --kind image
python3 scripts/boka_film.py models --kind video
python3 scripts/boka_film.py create-image --payload image.json --dry-run
python3 scripts/boka_film.py create-image --payload image.json
python3 scripts/boka_film.py create-video --payload video.json
python3 scripts/boka_film.py query --task-id TASK_ID
python3 scripts/boka_film.py wait --task-id TASK_ID --interval 10 --max-wait 1200
```

## 执行约束

- 参考素材字段使用服务端可访问的 HTTP(S) URL。说明没有上传接口；若只有本地素材，请获取可访问 URL 或使用用户已授权的上传方式。
- 创建项目和生成任务的 POST 只提交一次，不自动重试。请求超时或断连可能已创建项目或任务，先核查平台再决定是否重提。
- `wait` 默认最多等待 1200 秒，超时不取消远端任务。未知或空状态继续有界等待，不据此判断成功。
- API 业务码 `200` 仅代表请求成功；生成结果另看任务状态。脚本成功退出码为 0，错误/生成失败为 1，中断为 130。
