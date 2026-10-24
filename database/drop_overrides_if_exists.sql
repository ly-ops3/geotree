-- 迁移收尾：删除已废弃的 geo_place_label_overrides（在 geo_registry 库执行）
DROP TABLE IF EXISTS geo_place_label_overrides;
