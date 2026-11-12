-- Čištění ulic: the harmonogram of blokové čištění from Služby města Pardubic, for the whole
-- town (places are matched to obvody by their geometry), see petka/cisteni.

-- One place of the harmonogram (a Místo), keyed by its normalised text.
CREATE TABLE IF NOT EXISTS cleaning_places (
  key          text PRIMARY KEY,         -- normalised Místo (petka.cisteni.places.place_key)
  texts        text[] NOT NULL,          -- the wordings it had in the sheet
  pattern      text NOT NULL,            -- what kind of place the text describes
  main_street  text,                     -- RÚIAN name of the street it is listed under
  streets      text[] NOT NULL DEFAULT '{}',   -- every street the text names
  side         text,                     -- obe | prava | leva | NULL (not said)
  method       text,                     -- whole | segment | hull | block | override | NULL
  status       text NOT NULL,            -- auto | approx | partial | manual (no geometry or drawn by hand)
  geometry     jsonb,                    -- GeoJSON, WGS84
  obvody       jsonb NOT NULL DEFAULT '{}',    -- {"mo5": 0.93, …}: share of the place in each obvod
  note         text NOT NULL DEFAULT '',       -- how the geometry was found or why not
  updated_at   timestamptz NOT NULL DEFAULT now()
);

-- One cleaning of a place. Past dates stay when a new sheet drops them; future ones are
-- replaced by every new sheet.
CREATE TABLE IF NOT EXISTS cleaning_dates (
  place_key   text NOT NULL REFERENCES cleaning_places ON DELETE CASCADE,
  date        date NOT NULL,
  time        time,                       -- from (or, with before, by) this time; NULL = not said
  before      boolean NOT NULL DEFAULT false,   -- "před 6 hod."
  source_row  int NOT NULL,              -- row in the sheet
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (place_key, date)
);
CREATE INDEX IF NOT EXISTS cleaning_dates_date ON cleaning_dates (date);

-- Every download of the sheet we checked; the last one is "Stav k".
CREATE TABLE IF NOT EXISTS cleaning_sources (
  url         text NOT NULL,
  sha256      text NOT NULL,
  rows        int NOT NULL,
  checked_at  timestamptz NOT NULL DEFAULT now(),
  changed     boolean NOT NULL
);
CREATE INDEX IF NOT EXISTS cleaning_sources_checked ON cleaning_sources (checked_at DESC);

-- ČÚZK RÚIAN answers (streets, address points, obvody), misses too: asked once.
CREATE TABLE IF NOT EXISTS ruian_cache (
  key         text PRIMARY KEY,           -- as in petka.usneseni.geo ("street:<kod>", "cp:<n>" …)
  value       jsonb,
  fetched_at  timestamptz NOT NULL DEFAULT now()
);
