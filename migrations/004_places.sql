-- Places of resolutions as geometry (ČÚZK RÚIAN, built by petka.usneseni.geo into geo.json).
-- No PostGIS: few thousand features, GeoJSON as jsonb, a centroid and bbox for nearby queries.
CREATE TABLE IF NOT EXISTS resolution_places (
  id serial PRIMARY KEY,
  uid text NOT NULL REFERENCES resolutions(uid) ON DELETE CASCADE,
  kind text NOT NULL,            -- parcel | address | street
  label text NOT NULL,           -- official RÚIAN name ("Jana Palacha 324", "p. p. č. 2515/14, k. ú. Pardubice")
  source_text text,              -- the place as the minutes wrote it
  geometry jsonb NOT NULL,       -- GeoJSON geometry, WGS84
  lon double precision NOT NULL, -- centroid of the geometry's vertices
  lat double precision NOT NULL,
  bbox double precision[] NOT NULL  -- west, south, east, north
);
CREATE INDEX IF NOT EXISTS resolution_places_uid ON resolution_places (uid);
CREATE INDEX IF NOT EXISTS resolution_places_lonlat ON resolution_places (lon, lat);
