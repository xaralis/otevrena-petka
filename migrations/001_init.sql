-- Database is derived: `usneseni load` rebuilds rows from the data directory.
-- Embeddings are the only thing computed here and they survive reloads (keyed by text hash).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- unaccent() is STABLE; a wrapper pinned to the dictionary is IMMUTABLE so it can be indexed
CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
  AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;

CREATE TABLE IF NOT EXISTS members (
  id          text PRIMARY KEY,           -- filip-varecha
  name        text NOT NULL,              -- Ing. Filip Vařecha
  first_name  text NOT NULL,
  last_name   text NOT NULL,
  name_fold   text NOT NULL
);

CREATE TABLE IF NOT EXISTS memberships (
  member_id   text NOT NULL REFERENCES members(id),
  term        text NOT NULL,              -- 2022-2026
  list        text,                       -- electoral list
  elected     boolean NOT NULL,           -- won a seat at the election (else substitute)
  in_rada     boolean NOT NULL DEFAULT false,
  PRIMARY KEY (member_id, term)
);

CREATE TABLE IF NOT EXISTS meetings (
  id           text PRIMARY KEY,          -- zmo-2025-12-17-20
  body         text NOT NULL CHECK (body IN ('zmo', 'rmo')),
  term         text NOT NULL,
  number       int NOT NULL,
  kind         text NOT NULL,
  date         date NOT NULL,
  place        text,
  source_url   text NOT NULL,
  source_title text NOT NULL,
  status       text NOT NULL,             -- ok | needs_review
  issues       jsonb NOT NULL DEFAULT '[]',
  model_notes  jsonb NOT NULL DEFAULT '[]',
  present      text[] NOT NULL DEFAULT '{}',
  excused      text[] NOT NULL DEFAULT '{}',
  absent       text[] NOT NULL DEFAULT '{}',
  parsed_via   text,
  loaded_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS meetings_date ON meetings (date DESC);

CREATE TABLE IF NOT EXISTS agenda_items (
  meeting_id  text NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  seq         int NOT NULL,
  no          text NOT NULL,
  title       text NOT NULL,
  speakers    text[] NOT NULL DEFAULT '{}',
  discussion  text,                       -- derived summary
  PRIMARY KEY (meeting_id, seq)
);

CREATE TABLE IF NOT EXISTS resolutions (
  uid          text PRIMARY KEY,          -- 154-2025-z
  number       text NOT NULL,             -- 154/2025 Z
  meeting_id   text NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  body         text NOT NULL,
  date         date NOT NULL,
  seq          int NOT NULL,              -- order within the meeting
  agenda_no    text,
  agenda_title text,
  text         text NOT NULL,             -- verbatim from the PDF
  responsible  text,
  deadline     text,
  status       text NOT NULL CHECK (status IN ('prijato', 'neprijato', 'castecne', 'neovereno')),
  verbs        text[] NOT NULL DEFAULT '{}',
  -- derived (enrich); NULL until enriched
  title        text,
  summary      text,
  keywords     text[] NOT NULL DEFAULT '{}',
  topics       text[] NOT NULL DEFAULT '{}',
  kind         text,
  places       text[] NOT NULL DEFAULT '{}',
  parcels      text[] NOT NULL DEFAULT '{}',
  organizations text[] NOT NULL DEFAULT '{}',
  amounts      text[] NOT NULL DEFAULT '{}',
  -- search
  tsv          tsvector,
  embed_hash   text,
  embedding    vector(1024)
);
CREATE INDEX IF NOT EXISTS resolutions_meeting ON resolutions (meeting_id);
CREATE INDEX IF NOT EXISTS resolutions_date ON resolutions (date DESC);
CREATE INDEX IF NOT EXISTS resolutions_tsv ON resolutions USING gin (tsv);
CREATE INDEX IF NOT EXISTS resolutions_topics ON resolutions USING gin (topics);
CREATE INDEX IF NOT EXISTS resolutions_trgm ON resolutions USING gin (f_unaccent(lower(coalesce(title,'') || ' ' || text)) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS resolutions_embedding ON resolutions USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS votes (
  id             text PRIMARY KEY,        -- <meeting>-<seq>
  meeting_id     text NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
  seq            int NOT NULL,
  resolution_uid text REFERENCES resolutions(uid) ON DELETE CASCADE,
  part           text,
  subject        text,
  proposer       text,
  motion_text    text,
  procedural     boolean NOT NULL,
  n_pro          int NOT NULL,
  n_proti        int NOT NULL,
  n_zdrzel       int NOT NULL,
  n_nehlasoval   int,
  n_present      int NOT NULL,
  quorum         int NOT NULL,
  passed         boolean NOT NULL,
  outcome        text,                    -- prijato | neprijato | NULL (contradiction)
  stated_outcome text,
  ballots_status text NOT NULL,           -- complete | partial | tallies_only
  raw            text NOT NULL
);
CREATE INDEX IF NOT EXISTS votes_resolution ON votes (resolution_uid);
CREATE INDEX IF NOT EXISTS votes_meeting ON votes (meeting_id);

CREATE TABLE IF NOT EXISTS ballots (
  vote_id     text NOT NULL REFERENCES votes(id) ON DELETE CASCADE,
  member_id   text NOT NULL REFERENCES members(id),
  choice      text NOT NULL CHECK (choice IN ('pro','proti','zdrzel','nehlasoval','omluven','nepritomen')),
  provenance  text NOT NULL CHECK (provenance IN ('named','inferred','attendance')),
  PRIMARY KEY (vote_id, member_id)
);
CREATE INDEX IF NOT EXISTS ballots_member ON ballots (member_id);

-- Embeddings survive a reload: keyed by the hash of the embedded text.
CREATE TABLE IF NOT EXISTS embedding_cache (
  hash       text PRIMARY KEY,
  model      text NOT NULL,
  embedding  vector(1024) NOT NULL
);
