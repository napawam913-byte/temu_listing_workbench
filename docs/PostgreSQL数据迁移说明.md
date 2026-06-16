# PostgreSQL 数据迁移说明

本文档用于把本地 SQLite 数据库 `backend/data/app.db` 迁移到阿里云 RDS PostgreSQL。

## 当前迁移边界

- 迁移脚本只复制普通业务表。
- SQLite FTS 虚拟表会跳过，例如 `dxm_temu_category_search_fts`、`dxm_temu_attr_search_fts`。
- 迁移后先作为 PostgreSQL 数据备份与小规模上线准备，不会自动把后端运行库切到 PostgreSQL。
- 后端运行时切 PostgreSQL 需要继续改造 SQLite 专用 SQL，例如 `PRAGMA`、`INSERT OR REPLACE`、`?` 占位符、FTS 查询等。

## 1. 本地配置连接串

不要把真实密码提交到 Git。只在本地 `.env` 增加：

```env
DATABASE_URL=postgresql://temu_app:你的密码@pgm-bp10sp109p8t006rbo.pg.rds.aliyuncs.com:5432/temu_workbench
```

如果密码里包含特殊字符，例如 `@`、`:`、`/`、`#`、`?`，需要 URL 编码。

## 2. 安装 PostgreSQL 驱动

```powershell
cd D:\learning\temu_listing_workbench\backend
python -m pip install -r requirements.txt
```

## 3. 第一次全量迁移

第一次迁移到空库时建议使用 `--reset`，脚本会删除 PostgreSQL 中同名业务表并重建：

```powershell
cd D:\learning\temu_listing_workbench\backend
python scripts\migrate_sqlite_to_postgres.py --reset
```

脚本完成后会输出每张表的 SQLite 行数和 PostgreSQL 行数。

## 4. 增量补迁

后续如果只是把本地 SQLite 新数据补到 PostgreSQL，可以不加 `--reset`：

```powershell
cd D:\learning\temu_listing_workbench\backend
python scripts\migrate_sqlite_to_postgres.py
```

脚本会按主键执行 upsert。

## 5. 单表调试

```powershell
python scripts\migrate_sqlite_to_postgres.py --only-table products --only-table link_list_records
```

## 6. DataGrip 校验

迁移后可在 DataGrip 执行：

```sql
SELECT COUNT(*) FROM products;
SELECT COUNT(*) FROM product_pool_products;
SELECT COUNT(*) FROM link_list_records;
SELECT COUNT(*) FROM visual_generation_tasks;
```

## 7. 注意事项

- `.env`、`backend/data/`、`storage/` 已被 `.gitignore` 忽略，不要手动提交。
- 目前 PostgreSQL 是迁移目标，不是后端运行库。
- 真正上线运行 PostgreSQL 前，要做数据库访问层改造和回归测试。
