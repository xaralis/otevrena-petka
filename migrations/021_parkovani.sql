-- Parkování: the town's car parks from ChytřejšíParking (the operator's unofficial app API), their
-- free places live and the history of occupancy. See petka/parkovani and docs/parkovani.md.

-- Every daily build of the lots (`parkovani-update`): the source's facts of each lot as JSON. The
-- last accepted one is served; a refused one (fewer than 70 % of the last accepted) is kept.
CREATE TABLE IF NOT EXISTS parkovani_builds (
  id          serial PRIMARY KEY,
  built_at    timestamptz NOT NULL DEFAULT now(),
  lots        jsonb NOT NULL,             -- [{id, name, area, at, paid, description, number, locality, kind, capacity, prices}]
  total       int NOT NULL,
  accepted    boolean NOT NULL,
  reason      text,                       -- why it was refused
  report      jsonb                       -- what the build noticed (prices differing from the regulation, …)
);
CREATE INDEX IF NOT EXISTS parkovani_builds_accepted ON parkovani_builds (accepted, built_at DESC);

-- The free places of each lot as last fetched (`parkovani-obsazenost`, every 60 s). A failed fetch
-- changes nothing: the last good numbers stay.
CREATE TABLE IF NOT EXISTS parkovani_now (
  id          text PRIMARY KEY,           -- the operator's devID, as in the lots
  free        int NOT NULL,
  total       int NOT NULL,
  changed_at  timestamptz NOT NULL,       -- when Pětka last saw free or total change (the source gives no time)
  seen_at     timestamptz NOT NULL        -- the last fetch that had the lot
);

-- The fetcher's state: one row.
CREATE TABLE IF NOT EXISTS parkovani_state (
  one           boolean PRIMARY KEY DEFAULT true CHECK (one),
  fetched_at    timestamptz,              -- the last successful fetch
  tried_at      timestamptz,              -- the last attempt
  error         text,                     -- the last attempt's error, NULL when it succeeded
  failing_since timestamptz,              -- the first failure of the current run of failures
  alerted       boolean NOT NULL DEFAULT false
);

-- A small number for each lot, so that the history's rows stay small.
CREATE TABLE IF NOT EXISTS parkovani_lots (
  n           smallserial PRIMARY KEY,
  id          text UNIQUE NOT NULL
);

-- Occupancy about every 5 minutes, kept long: the first successful fetch in each 5-minute slot
-- writes the slot (`at` = its start). ~32 000 rows a day for 111 lots.
CREATE TABLE IF NOT EXISTS parkovani_history (
  lot         smallint NOT NULL REFERENCES parkovani_lots (n),
  at          timestamptz NOT NULL,
  free        smallint NOT NULL,
  total       smallint NOT NULL,
  PRIMARY KEY (lot, at)
);
CREATE INDEX IF NOT EXISTS parkovani_history_at ON parkovani_history (at);
