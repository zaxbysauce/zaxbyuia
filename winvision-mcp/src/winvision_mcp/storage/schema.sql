-- WinVision SQLite schema (v1).
-- Stored at ${data_dir}/winvision.sqlite

CREATE TABLE IF NOT EXISTS invocations (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts        TEXT    NOT NULL,
  tool      TEXT    NOT NULL,
  args_hash TEXT    NOT NULL,
  outcome   TEXT    NOT NULL,           -- "ok" | "error" | "blocked" | "dry_run"
  duration_ms INTEGER NOT NULL DEFAULT 0,
  error     TEXT
);
CREATE INDEX IF NOT EXISTS idx_invocations_ts ON invocations(ts);
CREATE INDEX IF NOT EXISTS idx_invocations_tool ON invocations(tool);

CREATE TABLE IF NOT EXISTS baselines (
  name         TEXT    PRIMARY KEY,
  window_title TEXT,
  created_at   TEXT    NOT NULL,
  png_path     TEXT    NOT NULL,
  width        INTEGER NOT NULL,
  height       INTEGER NOT NULL,
  dpi          REAL    NOT NULL DEFAULT 96.0,
  notes        TEXT,
  hash         TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  name        TEXT    PRIMARY KEY,
  created_at  TEXT    NOT NULL,
  script_path TEXT    NOT NULL,
  tool_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS assertions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  ts              TEXT    NOT NULL,
  description     TEXT    NOT NULL,
  passed          INTEGER NOT NULL,
  confidence      REAL    NOT NULL DEFAULT 0.0,
  reasoning       TEXT,
  screenshot_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_assertions_ts ON assertions(ts);
