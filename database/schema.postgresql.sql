-- Geo Registry — 地理名称库 canonical DDL（独立库，不含业务 users/moments）

BEGIN;

CREATE TABLE IF NOT EXISTS geo_places (
    id BIGSERIAL PRIMARY KEY,
    parent_id BIGINT REFERENCES geo_places(id),
    level SMALLINT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    iso_country CHAR(2),
    admin1_code TEXT,
    admin2_code TEXT,
    name_en TEXT,
    name_zh TEXT,
    name_local TEXT,
    pinyin TEXT,
    deep_legacy SMALLINT,
    is_selectable BOOLEAN NOT NULL DEFAULT TRUE,
    population INTEGER,
    sort_key TEXT,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_geo_places_parent ON geo_places(parent_id);
CREATE INDEX IF NOT EXISTS idx_geo_places_iso_country ON geo_places(iso_country);
CREATE INDEX IF NOT EXISTS idx_geo_places_name_zh ON geo_places(name_zh);
CREATE INDEX IF NOT EXISTS idx_geo_places_admin1 ON geo_places(iso_country, admin1_code);

-- ok_zh 源表：import_ok_zh 从此表写入 geo_places
CREATE TABLE IF NOT EXISTS ok_zh_level4 (
    id INTEGER PRIMARY KEY,
    pid INTEGER,
    deep INTEGER NOT NULL,
    name TEXT,
    pinyin_prefix TEXT,
    pinyin TEXT,
    ext_name TEXT NOT NULL
);

COMMIT;
