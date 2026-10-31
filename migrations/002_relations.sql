-- Resolution A revokes (rusi) or amends (meni) resolution B. Derived from A's verbatim text on
-- every load. `effective` = A itself passed (prijato/castecne); a voted-down revocation is kept
-- for the record but changes nothing. target_uid is NULL when B is older than the database.
CREATE TABLE IF NOT EXISTS resolution_relations (
  source_uid    text NOT NULL REFERENCES resolutions(uid) ON DELETE CASCADE,
  type          text NOT NULL CHECK (type IN ('rusi', 'meni')),
  target_number text NOT NULL,
  target_uid    text REFERENCES resolutions(uid) ON DELETE SET NULL,
  scope         text NOT NULL CHECK (scope IN ('cele', 'cast')),
  detail        text,
  effective     boolean NOT NULL,
  PRIMARY KEY (source_uid, type, target_number)
);
CREATE INDEX IF NOT EXISTS relations_target ON resolution_relations (target_uid);
