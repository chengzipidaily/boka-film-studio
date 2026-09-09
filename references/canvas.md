# 保存图片、视频到项目画布

依据 `bona-ai-inside-creativity` 前端实现整理：

- `src/stores/nodes.ts`：`addImageNode` / `addVideoNode` → `saveNodeData`。
- `src/utils/flowNodes.ts`：`NodeFactory.createImageNode` / `createVideoNode` 构建节点；`updateNodeResources` 将节点封装为资源数组。
- `src/api/flow-nodes/node-update.ts`：`fetchUpdateResourceLocationBatch` 提交资源数组。
- `src/api/project.ts`：读取画布列表和项目画布资源。
- `src/constants/flowNodes.ts`：默认画布为 `画布1`，节点默认宽度为 1024。

## 接口

统一使用 `https://api.bonanai.com/api/film/v1/film`，认证与其他 API 相同。

| 方法 | 相对路径 | 请求体 | 返回 data（前端类型） |
| --- | --- | --- | --- |
| POST | `/resource/canvas/list/{projectId}` | 无 | `[{"canvas":"画布1","updatedAt":"..."}]` |
| POST | `/resource/list/{projectId}` | 无 | `{"resourceLocationList":[...]}` |
| POST | `/resource/save/batch/{projectId}` | 资源数组 | 已保存资源数组 |

资源记录包含 `id`、`projectId`、`webLocation`、`canvas`、`status`、`createdAt`。注意 `/resource/list` 返回画布资源，与 `/resource/generated/list` 的生成任务记录用途不同。

保存是新增或更新指定 ID 的资源，不是替换整个画布。提交完整的待保存节点；不要把无关节点、连线或整个项目重新保存。

## 操作流程

1. 确认目标 `projectId`。保存生成结果时，先查询任务，只有 `status: 9` 才从 `result_url` 取媒体地址。已上传素材可直接使用 TOS 地址。
2. 执行 `canvas-list`、`canvas-resources`。按用户指定名称选择画布；未指定时可以采用唯一已有画布，没有已保存画布时使用前端默认 `画布1`。多个画布且上下文无法确定时，再向用户确认目标。
3. 新节点生成独立唯一 ID（例如 `uuid.uuid4().hex`），外层 `id` 与 `webLocation.id` 必须一致。不要把生成任务 ID 当作画布节点 ID。已知任务 ID 放进 `data.taskId`；仅上传的素材没有生成任务时设为空字符串。同一任务的多个结果分别创建节点。
4. 读取目标画布节点的位置和尺寸，避免重叠。空画布可采用前端起始位置 `{ "x": 240, "y": 120 }`；追加时可放在现有节点右侧并预留 50 间距。坐标属于画布坐标，不是浏览器屏幕坐标。尺寸已知时使用媒体实际宽高；图片尺寸未知可用前端兜底 1024×1024，并设 `imageSizeResolved: false`，供前端重新解析。视频尺寸未知时可省略 width/height，不伪造实际分辨率。
5. 将资源数组写入 JSON，用 `save-canvas --dry-run` 校验和预览，然后提交一次。保存用户选定的结果即可，不自动保存其他历史任务。
6. 用 `canvas-resources` 读取并核对本次节点的 ID、画布名、类型和媒体 URL。确认落库后报告项目、画布和节点 ID；页面可能需要刷新或切换画布才能重新加载。保存请求成功但核对失败时，说明尚未确认，不重复创建新 ID。

空画布不会落库，也不会出现在画布列表里。指定新画布名称保存首个资源即可建立有内容的画布，无需调用未提供的“创建画布”接口。

## 请求体示例

将以下内容保存为 `canvas.json`。示例 ID 和 URL 必须替换成实际值：

```json
[
  {
    "id": "unique-image-node-id",
    "canvas": "画布1",
    "webLocation": {
      "id": "unique-image-node-id",
      "type": "image",
      "position": {"x": 240, "y": 120},
      "data": {
        "taskId": "img_TASK_ID",
        "imageUrl": "https://example.com/result.png",
        "label": "春日图片",
        "width": 1024,
        "height": 1024,
        "imageSizeResolved": false
      }
    }
  },
  {
    "id": "unique-video-node-id",
    "canvas": "画布1",
    "webLocation": {
      "id": "unique-video-node-id",
      "type": "video",
      "position": {"x": 1314, "y": 120},
      "data": {
        "taskId": "VIDEO_TASK_ID",
        "videoUrl": "https://example.com/result.mp4",
        "label": "春日视频"
      }
    }
  }
]
```

`webLocation` 是 JSON 对象，不是 JSON 字符串；请求体最外层直接为数组，不包在 `resources` 或 `data` 对象中。画布名称在资源外层的 `canvas` 字段。此图片/视频保存链路没有额外的顶层 `resourceType`、`url` 或 `taskId` 字段。

CLI 当前只构建请求并校验 image/video 节点；布局、选择结果和编写 JSON 由 Skill 执行者根据现有资源完成。已知的 `toolData`、`requestParams`、`reeditDraft` 可保留；不猜测这些参数，也不带入 `selected`、`dragging` 等临时交互状态。

```bash
python3 scripts/boka_film.py canvas-list --project-id PROJECT_ID
python3 scripts/boka_film.py canvas-resources --project-id PROJECT_ID
python3 scripts/boka_film.py save-canvas --project-id PROJECT_ID --payload canvas.json --dry-run
python3 scripts/boka_film.py save-canvas --project-id PROJECT_ID --payload canvas.json
python3 scripts/boka_film.py canvas-resources --project-id PROJECT_ID
```

保存不会重新生成或上传媒体。仅查询或编写方案时不要写入画布。请求超时先查本次 ID 是否存在；重试时保留同一组 ID 和请求体，避免生成重复节点。用户要更新已有节点时，先读取原节点、合并所需变更后保存，保留其其他数据和画布归属。不要在画布改名后继续使用过期名称。
