-- What a traffic order on the úřední deska does and how long it holds, read from its PDF by the
-- deska job (petka.uredni_deska.measures). The posting dates are not the measure's validity.
-- Only dates, the reason, sign codes and our one-line wording: never the applicant or contacts.
CREATE TABLE IF NOT EXISTS notice_measures (
  notice_id    text PRIMARY KEY REFERENCES notices(id) ON DELETE CASCADE,
  attachments  jsonb NOT NULL,              -- the notice's attachments when read (read again when they change)
  valid_from   date,                        -- "Platnost úpravy" / "Termín"; NULL = the order doesn't say
  valid_to     date,
  reason       text,                        -- "Důvod": "stavební práce"
  signs        text[] NOT NULL DEFAULT '{}',  -- sign codes in the order of the document: Z2, B28, E8d
  what         text,                        -- "Uzavřená stezka kvůli stavebním pracím"
  read_at      timestamptz NOT NULL DEFAULT now()
);
