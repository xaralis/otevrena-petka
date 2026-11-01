-- Redaction now also drops the notice URL and file numbers of taken-down delivery notices.
UPDATE notices SET url = '', reference = NULL, file_mark = NULL WHERE redacted;
