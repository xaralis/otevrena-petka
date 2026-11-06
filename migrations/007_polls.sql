-- Indicative polls. A vote is stored under a hash of a random id the app keeps on the phone, so one
-- install has one vote and nothing identifies a person. A binding vote would need Identita občana.
CREATE TABLE polls (
    id text PRIMARY KEY,
    question text NOT NULL,
    description text,
    options jsonb NOT NULL,
    closes date,
    active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE poll_votes (
    poll_id text NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
    voter text NOT NULL,
    option integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (poll_id, voter)
);
INSERT INTO polls (id, question, description, options) VALUES
  ('co-v-aplikaci', 'Co by vám v aplikaci města pomohlo nejvíc?',
   'Ukázková anketa. Výsledek je jen orientační.',
   '["Živé odjezdy MHD", "Volná parkovací místa", "Připomínka svozu odpadu", "Hlášení závad a jejich stav", "Upozornění na uzavírky u mě"]');
