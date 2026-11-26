-- Místa: the kind of Průvodce městem a place is (pamatky, kultura, priroda, jidlo, ubytovani;
-- petka.mista.osm.guide_of, docs/mista.md), NULL for a place that is no place to visit.
ALTER TABLE mista_places ADD COLUMN IF NOT EXISTS pruvodce text;
