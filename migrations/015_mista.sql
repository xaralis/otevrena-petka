-- Místa: places of the whole town from OpenStreetMap (ODbL) – „Co je v okolí“, bike racks,
-- sorted-waste containers and recycling centres – rebuilt daily by `mista-update`, served as
-- /api/v1/mista (docs/mista.md). See petka/mista.

-- The places of the last accepted build; the job replaces them all in one transaction.
CREATE TABLE IF NOT EXISTS mista_places (
  id          text PRIMARY KEY,           -- OSM type letter (n|w|r) + OSM id
  kind        text NOT NULL,              -- potraviny … posta, stojan, kontejner, dvur
  name        text,                       -- NULL only for stojan, kontejner, dvur
  what        text NOT NULL,              -- what it is, in Czech
  address     text,                       -- street + number from addr:*
  lon         double precision NOT NULL,  -- a way's or relation's centre
  lat         double precision NOT NULL,
  hours       text,                       -- OSM opening_hours untouched
  obvody      text[] NOT NULL DEFAULT '{}',   -- the obvod it lies in ({} outside all)
  odpad       text[],                     -- kontejner, dvur: waste kinds it takes; else NULL
  capacity    int,                        -- stojan: OSM capacity; else NULL
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mista_places_kind ON mista_places (kind);

-- Every build from Overpass. The last accepted one is what is served (`built`); a refused one
-- (fewer than 70 % of the last accepted, in total or in a kind) is kept for the record.
CREATE TABLE IF NOT EXISTS mista_builds (
  id          serial PRIMARY KEY,
  built_at    timestamptz NOT NULL DEFAULT now(),
  counts      jsonb NOT NULL,             -- {kind: places}
  total       int NOT NULL,
  accepted    boolean NOT NULL,
  reason      text                        -- why it was refused
);
CREATE INDEX IF NOT EXISTS mista_builds_accepted ON mista_builds (accepted, built_at DESC);
