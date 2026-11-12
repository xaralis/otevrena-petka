-- When the office first and last wrote to a report (dates only, taken from Dej Tip's NOTE;
-- its text and the official's e-mail are never stored). For a closed report the last note
-- is about when it was closed, so "doba vyřízení" is known for reports older than our job.
ALTER TABLE citizen_reports ADD COLUMN IF NOT EXISTS first_note_at timestamp;
ALTER TABLE citizen_reports ADD COLUMN IF NOT EXISTS last_note_at timestamp;
