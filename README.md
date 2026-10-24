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
| `database/geo/` | GeoNames dump、`zh_altnames.sqlite`（中文别名索引，随仓库分发）、CLDR 区划中文名 | 部分入库 |
| `database/seed/geo_places.dump` | 主表完整 dump（`pg_dump -Fc` 压缩格式，~21MB）。用法：`pg_restore -U postgres -d geo_registry --clean --if-exists geo_places.dump` | 入库 |
| `database/seed/ok_zh_level4.pgdump.sql` | 国内区划种子（**PG 原生 dump**，`psql -f` 直接导入） | 入库 |
| `database/seed/ok_zh_level4.sql` | 同一份数据的 MySQL 方言原始备份（历史来源，参考用） | 入库 |
| `database/backups/` | 本地临时备份目录 | 整个目录 gitignore |
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

## 服务器部署

全部种子随仓库分发，clone 即有（数据库连接走环境变量，不落盘密码）：

```bash
git clone <repo> && cd geo-registry
pip install -r requirements.txt
createdb -U postgres geo_registry
export GEO_DB_DSN='postgresql://postgres@127.0.0.1:5432/geo_registry'

# 灌入种子数据（都在 database/seed/）
psql -U postgres -d geo_registry -f database/seed/ok_zh_level4.pgdump.sql
pg_restore -U postgres -d geo_registry --clean --if-exists database/seed/geo_places.dump

python app.py   # /health → geo_ready: true
```

种子更新方式：数据有变动后重新导出并提交——
`pg_dump -U postgres -d geo_registry -t geo_places -Fc -f database/seed/geo_places.dump`。
也可以完全不用种子，用 `python scripts/geo/import_all.py --profile standard` 从 GeoNames 全量重建（耗时长）。

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

## 数据来源与许可

本仓库包含第三方地理数据，使用时请遵守其原始许可：

| 数据 | 来源 | 许可 |
|------|------|------|
| GeoNames gazetteer / alternateNames | [geonames.org](https://www.geonames.org) | [CC-BY 4.0](https://creativecommons.org/licenses/by/4.0/)（需署名） |
| CLDR 行政区中文名 | [unicode-org/cldr-json](https://github.com/unicode-org/cldr-json) | Unicode License |
| ok_zh 国内区划（至街镇） | 第三方整理数据（MySQL dump） | 出处未明，公开分发前请确认可再分发性 |

代码本体采用 [MIT](LICENSE)。

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
