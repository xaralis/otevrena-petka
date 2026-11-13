-- The reporter's description with phone numbers and e-mail addresses masked, and the photo's
-- URL only where the reporter made it public on Dej Tip (decided 13. 11. 2026; see
-- docs/dejtip.md). The page loads the photo from Dej Tip, nothing is copied.
ALTER TABLE citizen_reports ADD COLUMN IF NOT EXISTS description text;
ALTER TABLE citizen_reports ADD COLUMN IF NOT EXISTS photo_url text;
