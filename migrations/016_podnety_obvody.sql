-- Podněty for the whole town: which obvody the job has mirrored, so the first run of an obvod
-- (two years back) happens once even for an obvod without a single report (see docs/dejtip.md).
CREATE TABLE IF NOT EXISTS citizen_report_obvody (
  obvod       text PRIMARY KEY,                     -- mo1 … mo8
  since       date NOT NULL,                        -- the earliest day downloaded for it
  checked_at  timestamptz NOT NULL DEFAULT now()    -- its last successful download; the API's ETag
);
-- Obvody mirrored before this table existed (MO V) are known already.
INSERT INTO citizen_report_obvody (obvod, since, checked_at)
SELECT obvod, min(reported_at)::date, max(last_seen) FROM citizen_reports GROUP BY obvod
ON CONFLICT (obvod) DO NOTHING;
