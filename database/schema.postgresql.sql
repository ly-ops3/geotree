-- Geo Registry — 地理名称库 canonical DDL（独立库，不含业务 users/moments）

BEGIN;

-- 语种枚举。code 是 ISO 639 / BCP 47（ja、zh-CN），英文名只存一次。
CREATE TABLE IF NOT EXISTS geo_languages (
    code TEXT PRIMARY KEY,
    iso639 TEXT NOT NULL,
    name_en TEXT
);

CREATE TABLE IF NOT EXISTS geo_places (
    id BIGSERIAL PRIMARY KEY,
    parent_id BIGINT REFERENCES geo_places(id),
    level SMALLINT NOT NULL,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    iso_country CHAR(2),
    admin1_code TEXT,
    admin2_code TEXT,
    feature_class CHAR(1),
    feature_code TEXT,
    name_en TEXT,
    name_zh TEXT,
    name_zh_hant TEXT,
    name_base TEXT,
    name_local TEXT,
    name_local_lang TEXT REFERENCES geo_languages(code),
    pinyin TEXT,
    deep_legacy SMALLINT,
    is_selectable BOOLEAN NOT NULL DEFAULT TRUE,
    population INTEGER,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    area_km2 INTEGER,
    capital TEXT,
    continent CHAR(2),
    sort_key TEXT,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_geo_places_parent ON geo_places(parent_id);
CREATE INDEX IF NOT EXISTS idx_geo_places_iso_country ON geo_places(iso_country);
CREATE INDEX IF NOT EXISTS idx_geo_places_name_zh ON geo_places(name_zh);
CREATE INDEX IF NOT EXISTS idx_geo_places_name_base ON geo_places(name_base);
CREATE INDEX IF NOT EXISTS idx_geo_places_admin1 ON geo_places(iso_country, admin1_code);

-- 每个地点、每种语言一条首选名称。name_local 是其中主语言那条的冗余，方便列表不 JOIN。
CREATE TABLE IF NOT EXISTS geo_place_names (
    place_id BIGINT NOT NULL REFERENCES geo_places(id) ON DELETE CASCADE,
    lang_code TEXT NOT NULL REFERENCES geo_languages(code),
    name TEXT NOT NULL,
    is_preferred BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (place_id, lang_code)
);

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
