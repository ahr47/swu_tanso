-- 탄소줄이슈 DB 스키마 (백엔드1) — API 필드명세서 v02 기준
-- PostgreSQL 14+ / PGlite. 실행 순서: schema.sql -> seed.sql  (python -m db --reset)

DROP TABLE IF EXISTS recommendations;
DROP TABLE IF EXISTS scenario_items;
DROP TABLE IF EXISTS scenarios;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS emission_factors;
DROP TABLE IF EXISTS item_variants;
DROP TABLE IF EXISTS items;
DROP SEQUENCE IF EXISTS event_id_seq;
DROP SEQUENCE IF EXISTS scenario_id_seq;
DROP SEQUENCE IF EXISTS rec_id_seq;

-- ---------------------------------------------------------------------------
-- 품목 마스터·배출계수 (데이터: 백엔드3 calculator/catalogue_v02.json -> seed.sql)
-- ---------------------------------------------------------------------------
CREATE TABLE items (
    item_id      TEXT PRIMARY KEY,
    item_name    TEXT NOT NULL,
    category     TEXT NOT NULL,
    input_unit   TEXT NOT NULL,
    calc_type    TEXT NOT NULL CHECK (calc_type IN ('COUNT', 'AREA')),
    input_method TEXT NOT NULL CHECK (input_method IN ('count_only', 'count_variant', 'dimension', 'fixed_use')),
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    notes        JSONB NOT NULL DEFAULT '[]',
    description  TEXT,
    sort_order   INT NOT NULL DEFAULT 0
);

CREATE TABLE item_variants (
    item_id    TEXT NOT NULL REFERENCES items (item_id) ON DELETE CASCADE,
    variant    TEXT NOT NULL,
    label      TEXT NOT NULL,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order INT NOT NULL DEFAULT 0,
    PRIMARY KEY (item_id, variant)
);
-- 품목당 기본 변형은 최대 1개
CREATE UNIQUE INDEX uq_item_variants_default ON item_variants (item_id) WHERE is_default;

-- 변형 없는 품목의 계수 키는 variant = 'default'. 버전별로 보관 (CURRENT_FACTOR_VERSION 으로 선택)
CREATE TABLE emission_factors (
    item_id        TEXT NOT NULL REFERENCES items (item_id) ON DELETE CASCADE,
    variant        TEXT NOT NULL,
    factor_version TEXT NOT NULL,
    value          NUMERIC(18, 8) CHECK (value >= 0),   -- NULL 이면 계산 불가 (CALC_NOT_AVAILABLE)
    unit           TEXT NOT NULL,
    calc_type      TEXT NOT NULL CHECK (calc_type IN ('COUNT', 'AREA')),
    source_name    TEXT NOT NULL,
    source_url     TEXT,
    source_year    INT,
    confidence     TEXT,
    notes          JSONB NOT NULL DEFAULT '[]',
    scope_group    TEXT,
    PRIMARY KEY (item_id, variant, factor_version)
);

-- ---------------------------------------------------------------------------
-- 행사·시나리오·추천 (ID 형식: EVT_0001, SCN_0001, REC_1)
-- ---------------------------------------------------------------------------
CREATE SEQUENCE event_id_seq;
CREATE SEQUENCE scenario_id_seq;
CREATE SEQUENCE rec_id_seq;

CREATE TABLE events (
    event_id     TEXT PRIMARY KEY DEFAULT 'EVT_' || lpad(nextval('event_id_seq')::text, 4, '0'),
    event_name   TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    participants INT  NOT NULL CHECK (participants >= 1),
    budget       BIGINT CHECK (budget >= 0),
    event_date   DATE,
    location     TEXT,
    description  TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 행사당 original 1개 + improved 최대 1개. version 은 품목 저장 때마다 +1 (추천 유효성 확인용)
CREATE TABLE scenarios (
    scenario_id   TEXT PRIMARY KEY DEFAULT 'SCN_' || lpad(nextval('scenario_id_seq')::text, 4, '0'),
    event_id      TEXT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    scenario_type TEXT NOT NULL CHECK (scenario_type IN ('original', 'improved')),
    version       INT  NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (event_id, scenario_type)
);

CREATE TABLE scenario_items (
    scenario_id TEXT NOT NULL REFERENCES scenarios (scenario_id) ON DELETE CASCADE,
    position    INT  NOT NULL,                       -- 입력 순서
    item_id     TEXT NOT NULL REFERENCES items (item_id),
    quantity    INT  NOT NULL CHECK (quantity >= 1),
    variant     TEXT,
    width_m     DOUBLE PRECISION CHECK (width_m > 0),
    height_m    DOUBLE PRECISION CHECK (height_m > 0),
    unit_price  INT CHECK (unit_price >= 0),
    PRIMARY KEY (scenario_id, position),
    UNIQUE (scenario_id, item_id)                    -- 같은 품목 중복 금지 (DUPLICATE_ITEM)
);

CREATE TABLE recommendations (
    rec_id                TEXT PRIMARY KEY DEFAULT 'REC_' || nextval('rec_id_seq')::text,
    event_id              TEXT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    scenario_id           TEXT NOT NULL REFERENCES scenarios (scenario_id) ON DELETE CASCADE,
    base_version          INT  NOT NULL,             -- 추천 생성 시점 original version
    position              INT  NOT NULL,
    item_id               TEXT NOT NULL REFERENCES items (item_id),
    item_name             TEXT NOT NULL,
    category              TEXT NOT NULL,
    action_type           TEXT NOT NULL CHECK (action_type IN ('reduce_quantity', 'replace_item')),
    target_field          TEXT NOT NULL CHECK (target_field IN ('quantity', 'item_id')),
    current_value         INT,
    recommended_value     INT,
    alternative_item_id   TEXT REFERENCES items (item_id),
    alternative_item_name TEXT,
    alternative_variant   TEXT,
    title                 TEXT NOT NULL,
    difficulty            TEXT NOT NULL CHECK (difficulty IN ('쉬움', '보통', '어려움')),
    reason                TEXT NOT NULL DEFAULT '',
    emission_reduction    NUMERIC(18, 8),
    cost_change           BIGINT,
    applicable            BOOLEAN NOT NULL,
    not_applicable_reason TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_recommendations_event ON recommendations (event_id, position);
