-- Dopravní informace NDIC (ŘSD): the snapshot "DATEX II – Běžné dopravní informace" (closures,
-- road works, accidents…) for the whole town; each record knows the obvody it touches, see
-- petka/uzavirky. Only what we show is kept: no TMC locations, no raw messages.

-- One situation record of the snapshot, keyed by its DATEX id. A record that drops out of the
-- snapshot is over (gone_at); it stays for the street pages' history.
CREATE TABLE IF NOT EXISTS traffic_records (
  id           text PRIMARY KEY,         -- situationRecord/@id
  situation    text NOT NULL,            -- situation/@id (records of one situation belong together)
  version      int NOT NULL,             -- situationRecord/@version
  kind         text NOT NULL,            -- xsi:type: RoadOrCarriagewayOrLaneManagement, Accident, …
  details      text[] NOT NULL DEFAULT '{}',   -- its *Type values: roadClosed, laneClosures, …
  starts_at    timestamptz,              -- overallStartTime
  ends_at      timestamptz,              -- overallEndTime (NULL: not said)
  comment      text NOT NULL DEFAULT '', -- generalPublicComment in Czech, as NDIC wrote it
  source       text NOT NULL DEFAULT '', -- sourceName (Policie ČR, Operátoři NDIC, …)
  road         text,                     -- roadNumber, if any
  geometry     jsonb,                    -- GeoJSON, WGS84: the stretch on the street, or the points
  method       text NOT NULL,            -- street | straight | point: how the geometry was made
  obvody       jsonb NOT NULL DEFAULT '{}',    -- {"mo5": 0.8, …}: share in each obvod of the town
  version_at   timestamptz,              -- situationRecordVersionTime
  first_seen   timestamptz NOT NULL DEFAULT now(),
  last_seen    timestamptz NOT NULL DEFAULT now(),
  gone_at      timestamptz               -- dropped out of the snapshot
);
CREATE INDEX IF NOT EXISTS traffic_records_live ON traffic_records (gone_at, ends_at);

-- Every snapshot we downloaded; the last one is "Stav k".
CREATE TABLE IF NOT EXISTS traffic_snapshots (
  published_at  timestamptz,             -- publicationTime
  sha256        text NOT NULL,
  records       int NOT NULL,            -- in the whole snapshot (the country)
  in_town       int NOT NULL,            -- of them in the town
  changed       boolean NOT NULL,
  checked_at    timestamptz NOT NULL DEFAULT now()
);
