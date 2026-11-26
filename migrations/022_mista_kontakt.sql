-- Místa: how to reach a place, from OSM phone/contact:phone, website/contact:website (else its
-- Facebook or Instagram page) and email/contact:email (docs/mista.md). NULL where OSM has none.
ALTER TABLE mista_places ADD COLUMN IF NOT EXISTS phone text;
ALTER TABLE mista_places ADD COLUMN IF NOT EXISTS web text;
ALTER TABLE mista_places ADD COLUMN IF NOT EXISTS email text;
