-- Místa: opening hours (and a phone or a web) from open sources for places whose OSM object has
-- none – All The Places, the place's own web (schema.org), the town's hand-kept list – rebuilt
-- weekly by `mista-doplnky` (petka.mista.doplnky, docs/mista.md). The export uses a row only where
-- OSM has no opening_hours; of two sources for a place, mesto before alltheplaces before web.
CREATE TABLE IF NOT EXISTS mista_doplnky (
  id          text NOT NULL,              -- the place's id in mista_places
  source      text NOT NULL,              -- mesto | alltheplaces | web
  hours       text,                       -- opening_hours in OSM syntax
  phone       text,
  web         text,
  url         text,                       -- the page the hours are from (web, mesto)
  checked_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, source)
);
