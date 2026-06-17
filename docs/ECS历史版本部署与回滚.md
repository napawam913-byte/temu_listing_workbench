# ECS 历史版本部署与回滚

当前部署改为 release 目录模式，避免每次部署直接覆盖线上代码。

## 目录结构

默认部署根目录：

```bash
/opt/temu_listing_workbench
```

部署后结构：

```bash
/opt/temu_listing_workbench/
  current -> releases/20260617170000-45e555d
  releases/
    20260617165000-ba6db98
    20260617170000-45e555d
  shared/
    .env
    storage/
    backend_runtime/
```

- `current`：当前线上运行版本。
- `releases`：历史代码版本，每次 GitHub Actions 手动部署都会新增一个目录。
- `shared/.env`：线上环境变量，不随代码版本切换。
- `shared/storage`：上传、导出、生图等运行文件，不随代码版本切换。

## 部署方式

GitHub Actions 现在只支持手动部署：

1. 打开 GitHub 仓库。
2. 进入 `Actions`。
3. 选择 `Deploy ECS`。
4. 点击 `Run workflow`。
5. `deploy_ref` 可填：
   - `main`
   - 某个 commit hash
   - tag 名

部署成功后，服务器会生成一个 release，例如：

```bash
/opt/temu_listing_workbench/releases/20260617170000-45e555d
```

健康检查通过后，`current` 会切换到这个 release。

## 查看历史版本

在 ECS 终端执行：

```bash
bash /opt/temu_listing_workbench/current/scripts/rollback_server.sh --list
```

输出中带 `*` 的是当前运行版本。

## 回滚到指定版本

例如要回滚到：

```bash
20260617165000-ba6db98
```

执行：

```bash
bash /opt/temu_listing_workbench/current/scripts/rollback_server.sh 20260617165000-ba6db98
```

脚本会做三件事：

1. 把 `current` 指向目标 release。
2. 重启 `temu-workbench` 后端服务。
3. reload nginx 并检查 `/api/health` 和首页。

## 注意事项

- 回滚只回滚代码和前端页面。
- 云数据库 RDS 不会跟着回滚。
- 如果某个版本执行过数据库结构变更，回滚代码前需要确认旧代码是否兼容当前数据库。
- `.env` 不放在 release 里，统一放在 `shared/.env`。
- 导出文件、生图文件等运行数据放在 `shared/storage`，不会因为回滚丢失。
