-- Úřední deska: notices from the official boards (OFN "Úřední deska" JSON), with history.
-- A notice that drops out of its board's feed gets removed_at (sejmuto); it is not deleted.

CREATE TABLE IF NOT EXISTS notice_boards (
  id             text PRIMARY KEY,         -- mo5 | mmp
  name           text NOT NULL,
  url            text NOT NULL,            -- JSON feed
  page           text NOT NULL,            -- the board on pardubice.eu
  etag           text,
  last_modified  text,
  sha256         text,                     -- of the last downloaded document
  checked_at     timestamptz,              -- last successful download
  changed_at     timestamptz,              -- last time the document differed
  n_items        int
);

CREATE TABLE IF NOT EXISTS notices (
  id           text PRIMARY KEY,           -- <board>-<id in the source URL>, e.g. mo5-15531
  board        text NOT NULL REFERENCES notice_boards(id),
  url          text NOT NULL,              -- the notice on pardubice.eu (its OFN url)
  title        text NOT NULL,
  published    date,                       -- vyvěšení
  valid_until  date,                       -- relevantní do (planned sejmutí)
  agenda       text[] NOT NULL DEFAULT '{}',
  kind         text NOT NULL,              -- ours, from the title (source.KINDS)
  reference    text,                       -- číslo jednací
  file_mark    text,                       -- spisová značka
  department   text,                       -- odbor (Pardubice extension of the OFN)
  attachments  jsonb NOT NULL DEFAULT '[]',  -- [{title, url}], the city's file URLs
  is_mo5       boolean NOT NULL,
  redacted     boolean NOT NULL DEFAULT false,  -- name of a person dropped after sejmutí
  first_seen   timestamptz NOT NULL DEFAULT now(),
  last_seen    timestamptz NOT NULL DEFAULT now(),
  removed_at   timestamptz,                -- gone from the feed; NULL = posted now
  -- unaccented `simple` like the resolutions (f_unaccent from 001_init.sql)
  tsv          tsvector GENERATED ALWAYS AS (
                 setweight(to_tsvector('simple', f_unaccent(lower(title))), 'A') ||
                 setweight(to_tsvector('simple', f_unaccent(lower(coalesce(reference, '') || ' ' ||
                   coalesce(department, '')))), 'B')
               ) STORED
);
CREATE INDEX IF NOT EXISTS notices_published ON notices (published DESC);
CREATE INDEX IF NOT EXISTS notices_active ON notices (board) WHERE removed_at IS NULL;
CREATE INDEX IF NOT EXISTS notices_tsv ON notices USING gin (tsv);
