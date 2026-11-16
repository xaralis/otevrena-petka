-- Podněty: the public photos, shrunk and served by the portal (podnety/photos.py, docs/dejtip.md).
-- Only a photo the reporter made public; it goes when the report loses it or is deleted. A row
-- without an image is a download that failed (404, not an image) and waits before another try.
CREATE TABLE IF NOT EXISTS citizen_report_photos (
  id          bigint PRIMARY KEY REFERENCES citizen_reports ON DELETE CASCADE,
  source_url  text NOT NULL,                        -- the photo_url it was made from
  image       bytea,                                -- WebP, longer side <= 800 px, no EXIF/GPS
  version     text,                                 -- start of the image's SHA-256: its URL and ETag
  error       text,                                 -- why the download failed (image NULL)
  fetched_at  timestamptz NOT NULL DEFAULT now(),
  CHECK ((image IS NULL) = (version IS NULL))
);
