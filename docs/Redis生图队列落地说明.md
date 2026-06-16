# Redis 生图队列落地说明

本阶段只把「视觉生图任务」接入 Redis 队列，不改变商品池、数据台、链接列表和 Excel 导出的数据事实来源。数据库仍然是最终状态库，Redis 只负责排队、延迟重试和短期进度。

## 启用配置

```env
REDIS_URL=redis://127.0.0.1:6379/0
VISUAL_QUEUE_REDIS_ENABLED=1
VISUAL_QUEUE_NAME=visual:tasks:queue
VISUAL_QUEUE_RETRY_NAME=visual:tasks:retry
VISUAL_QUEUE_DEAD_NAME=visual:tasks:dead
VISUAL_QUEUE_DRAIN_MAX_JOBS=3
VISUAL_QUEUE_WORKER_LOCK_SECONDS=3600
VISUAL_QUEUE_POP_TIMEOUT_SECONDS=1
VISUAL_QUEUE_MAX_RETRIES=2
VISUAL_QUEUE_RETRY_DELAY_SECONDS=30
VISUAL_USER_CONCURRENCY_LIMIT=5
VISUAL_TEAM_CONCURRENCY_LIMIT=5
```

`VISUAL_QUEUE_REDIS_ENABLED=0` 或 Redis 不可用时，系统会回退到 FastAPI `BackgroundTasks`。小规模上线建议一定打开 Redis，并单独启动 worker。

## 执行链路

```text
前端点击主图全量生成 / SKU 适配
后端创建 visual_generation_tasks 记录
调用 /api/visual/tasks/{id}/run
任务状态写入 queued
优先推入 Redis 主队列
worker 消费任务
执行 plan -> generate -> split -> OSS -> 回写链接列表
成功写 completed
失败先写 retry_waiting，并进入延迟重试队列
超过重试次数后写 failed，并进入 dead queue
```

## 独立 Worker

线上建议后端 API 和 worker 分开常驻：

```bash
python backend/scripts/run_visual_queue_worker.py
```

本地只验证一次：

```bash
python backend/scripts/run_visual_queue_worker.py --once
```

如果需要控制每轮最多处理多少任务：

```bash
python backend/scripts/run_visual_queue_worker.py --max-jobs 2
```

## 队列状态

前端任务队列弹窗会读取：

```http
GET /api/visual/queue/summary
```

返回内容包含：

- 当前用户各状态任务数
- 团队 active 任务数
- 用户并发上限
- 团队并发上限
- Redis 主队列长度
- Redis 延迟重试队列长度
- Redis 死信队列长度

## 状态说明

| 状态 | 含义 |
| --- | --- |
| `draft` | 任务已创建，尚未执行 |
| `queued` | 已进入执行队列 |
| `running` | worker 正在执行 |
| `retry_waiting` | 执行失败，等待延迟重试 |
| `planned` | 已生成规划或母图提示词 |
| `split` | 母图已切割但不一定全部回写 |
| `completed` | 已完成并回写 |
| `failed` | 超过重试次数或不可恢复失败 |

## 数据边界

数据库仍然是最终事实来源：

- `visual_generation_tasks` 保存任务状态、输入快照、提示词、母图、错误信息。
- `visual_generation_modules` 保存切割后的每张图、槽位和回写状态。
- Redis 只保存待执行任务、延迟重试任务、死信任务和短期进度。

这样即使 Redis 缓存异常，也不会污染商品池、链接列表或 Excel 导出数据。
