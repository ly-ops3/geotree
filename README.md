# Geo Registry

独立的全球地理名称库服务（Flask + PostgreSQL）：一棵 `geo_places` 树承载
GeoNames 全球区划 + ok_zh 国内区划（到街镇）+ 大区映射，
对外提供统一的 `place_id`、级联浏览、中英文搜索与自由文本解析 API。

设计目标：多个应用共用同一份地理数据与 `place_id` 语义——业务库只存
`location_place_id`，地名展示/编辑全部走本服务。

## 快速开始

```bash
# 1. 建库
psql -U postgres -c "CREATE DATABASE geo_registry"

# 2. 依赖
pip install -r requirements.txt

# 3. 配置：复制示例并按需修改（config.json 已 gitignore）
cp config.example.json config.json

# 4. 启动（首次启动自动建表），默认 http://127.0.0.1:5010
python app.py

# 5. 导入数据（可选；联网自动下载 GeoNames 源文件）
python scripts/geo/import_all.py --profile standard
```

## 配置

优先级：环境变量 > `config.json` > 内置默认值。

| 配置 | 说明 |
|------|------|
| `database.*` | PostgreSQL 连接（host/port/name/user/password/pool_size） |
| `api.*` | 监听 host/port、debug、threaded |
| `bind_mode` | `local` = 仅 127.0.0.1；其他值按 `api.host` 监听 |
| `data_dir` | GeoNames/中文名源数据目录，空 = `./database/geo`，支持相对/绝对路径 |
| `cors_origins` | 允许跨域的前端源 |

环境变量：`GEO_DB_DSN`（`postgresql://user:pass@host:port/name`）或单项
`GEO_DB_HOST` / `GEO_DB_PORT` / `GEO_DB_NAME` / `GEO_DB_USER` / `GEO_DB_PASSWORD`，
以及 `GEO_DATA_DIR`。

## 数据文件

运行时**不依赖**源文件——`geo_places` / `ok_zh_level4` 都在 PostgreSQL 里，
源文件只是导入输入：

| 路径 | 说明 | 是否入库 |
|------|------|----------|
| `database/geo/` | GeoNames dump、`zh_altnames.sqlite`（中文别名索引）、CLDR 区划中文名 | 默认 gitignore，`import_all.py` 可重新下载，或 `data_dir` 指向外部目录 |
| `database/seed/ok_zh_level4.sql` | 国内区划种子备份（**MySQL 方言 dump**，导入 PG 需转换类型；也可用 `migrate_from_moments.py` 从旧库直接复制） | 入库 |
| `database/schema.postgresql.sql` | 全量 DDL，空库自动执行 | 入库 |

## API

| 端点 | 说明 |
|------|------|
| `GET /health` | 健康检查（含 `geo_ready`） |
| `GET /api/geo/regions` | 级联子节点（`scope` / `parent_id`） |
| `GET /api/geo/regions/search` | 搜索（兼容旧路径） |
| `GET /api/places/search` | 按中英文名称搜索 |
| `GET /api/geo/regions/{id}/path` | 面包屑 |
| `GET /api/places/{id}` | 单条元数据 |
| `GET /api/places/{id}/path` | 面包屑（推荐） |
| `POST /api/places/validate` | 写入前校验 `place_id` |

## 目录结构

```
app.py                  API 入口
app/config.py           配置加载（config.json + 环境变量）
app/db.py               PG 连接与 schema 初始化
app/geo/                区划查询、中文名解析、大区映射、自由文本解析
app/handlers/geo.py     HTTP 路由
scripts/geo/            导入脚本（GeoNames、ok_zh）
scripts/                建库与历史迁移辅助
database/               schema + geo 源数据缓存 + seed
```

## 附录：从 moments_pro 迁入

若你的地理表还在旧库（如 `moments_pro`）里：

```bash
python scripts/setup_db.py
python scripts/migrate_from_moments.py --dry-run
python scripts/migrate_from_moments.py --force
python app.py   # /health → geo_ready: true
```

迁移收尾（手动迁移完成后）：`python scripts/finish_migration.py`
会清理废弃表、同步序列并核对旧库已无本地地理表。
