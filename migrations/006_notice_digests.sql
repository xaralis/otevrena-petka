-- Úřední deska "pro lidi": plain-language digests of notices (petka.uredni_deska.digest).
-- Loaded from data/uredni_deska/{digests,drafts}/<id>/digest.json; the files are the source.
CREATE TABLE IF NOT EXISTS notice_digests (
  notice_id      text PRIMARY KEY REFERENCES notices(id) ON DELETE CASCADE,
  members        text[] NOT NULL DEFAULT '{}',   -- annexes posted separately, shown inside this card
  status         text NOT NULL CHECK (status IN ('draft', 'published', 'rejected')),
  cluster        text NOT NULL,
  data           jsonb NOT NULL,                 -- the whole digest.json
  prompt_version text,
  created_at     timestamptz,
  published_at   timestamptz,
  review_note    text
);
CREATE INDEX IF NOT EXISTS notice_digests_status ON notice_digests (status);
CREATE INDEX IF NOT EXISTS notice_digests_members ON notice_digests USING gin (members);
