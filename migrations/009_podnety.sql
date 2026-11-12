-- Podněty: citizens' reports from the city's Dej Tip app, mirrored per obvod (see docs/dejtip.md).
-- Only what a public map needs: what, where (street without house number), when and how it
-- stands. Never the reporter's comment, the office's notes, photos, devices or logins.

CREATE TABLE IF NOT EXISTS citizen_reports (
  id                 bigint PRIMARY KEY,       -- INCIDENTID in Dej Tip
  obvod              text NOT NULL,            -- mo5 …
  momc               int  NOT NULL,            -- CS_MUNICODE (RÚIAN code of the obvod)
  category_id        int  NOT NULL,
  category           text NOT NULL,            -- as Dej Tip names it (Chodník, Veřejná zeleň …)
  status             int  NOT NULL,            -- Dej Tip's status codelist (1 Evidováno … 9)
  reported_at        timestamp NOT NULL,       -- TIP_DATE, local time as the source gives it
  lat                double precision NOT NULL,
  lng                double precision NOT NULL,
  street             text,                     -- street only; NULL where the address isn't one
  first_seen         timestamptz NOT NULL DEFAULT now(),
  last_seen          timestamptz NOT NULL DEFAULT now(),   -- last download that had it
  status_changed_at  timestamptz               -- when we saw the status change; NULL = never yet
);
CREATE INDEX IF NOT EXISTS citizen_reports_obvod ON citizen_reports (obvod, reported_at DESC);
CREATE INDEX IF NOT EXISTS citizen_reports_position ON citizen_reports (lat, lng);

-- Every status a report had, with when we first saw it. The first row of a report is
-- `initial`: the report already had that status when we found it, so its date is only an
-- upper bound. Later rows are changes seen by the daily job (to the day), which is what
-- "doba vyřízení" can be measured from.
CREATE TABLE IF NOT EXISTS citizen_report_statuses (
  id        bigint NOT NULL REFERENCES citizen_reports ON DELETE CASCADE,
  status    int  NOT NULL,
  seen_at   timestamptz NOT NULL DEFAULT now(),
  initial   boolean NOT NULL,
  PRIMARY KEY (id, seen_at)
);
