-- Rozpočet: the city's rozklikávací rozpočet (GORDIC) per unit (mmp, mo1 … mo8) and year.
-- Amounts are thousands of Kč with two decimals, as the source gives them. A year's rows are
-- replaced as a whole on every change; budget_snapshots keeps each distinct download.

CREATE TABLE IF NOT EXISTS budget_years (
  unit         text NOT NULL,              -- mo5 | mmp | mo1 …
  year         int  NOT NULL,
  as_of        date NOT NULL,              -- "Stav ke dni" of the last download
  checked_at   timestamptz NOT NULL,       -- last successful download
  changed_at   timestamptz NOT NULL,       -- last time the content differed
  sha256       text NOT NULL,              -- of the parsed content, not the files (they carry the date)
  PRIMARY KEY (unit, year)
);

CREATE TABLE IF NOT EXISTS budget_snapshots (
  unit         text NOT NULL,
  year         int  NOT NULL,
  report       text NOT NULL,              -- rekapitulace | odvetvi | polozky | faktury
  as_of        date NOT NULL,
  fetched_at   timestamptz NOT NULL DEFAULT now(),
  xlsx         bytea NOT NULL,             -- the export as downloaded, for re-parsing later
  PRIMARY KEY (unit, year, report, as_of)
);

CREATE TABLE IF NOT EXISTS budget_totals (
  unit      text NOT NULL,
  year      int  NOT NULL,
  kind      text NOT NULL,                 -- prijmy | vydaje | financovani
  approved  numeric(14,2) NOT NULL,        -- schválený rozpočet
  revised   numeric(14,2) NOT NULL,        -- upravený rozpočet
  actual    numeric(14,2) NOT NULL,        -- skutečnost
  PRIMARY KEY (unit, year, kind)
);

CREATE TABLE IF NOT EXISTS budget_sectors (
  unit      text NOT NULL,
  year      int  NOT NULL,
  sector    text NOT NULL,                 -- odvětví as the site names it (Doprava, Kultura …)
  approved  numeric(14,2) NOT NULL,
  revised   numeric(14,2) NOT NULL,
  actual    numeric(14,2) NOT NULL,
  PRIMARY KEY (unit, year, sector)
);

-- Invoices paid (profinancováno) with the classification of the rozpočtová skladba. The
-- source has no supplier, date or document number; `n` is the order in the report.
CREATE TABLE IF NOT EXISTS budget_invoices (
  unit            text NOT NULL,
  year            int  NOT NULL,
  n               int  NOT NULL,
  "group"         int  NOT NULL,           -- skupina (first digit of the paragraf)
  group_name      text NOT NULL,
  paragraph       int  NOT NULL,           -- paragraf (odvětvové třídění)
  paragraph_name  text NOT NULL,
  item            int  NOT NULL,           -- položka (druhové třídění)
  item_name       text NOT NULL,
  description     text NOT NULL,           -- the office's own text; may be empty
  amount          numeric(14,2) NOT NULL,
  PRIMARY KEY (unit, year, n)
);
CREATE INDEX IF NOT EXISTS budget_invoices_paragraph ON budget_invoices (unit, year, paragraph);

-- The budget itself by odbor, paragraf and položka (RROZROZK0032 "výdaje dle odborů"). The
-- report has names only; codes are mapped from the MF codelists (data/rozpocet/ciselnik.json)
-- and stay NULL where a name isn't a paragraf / položka (e.g. the office's own "úroky").
CREATE TABLE IF NOT EXISTS budget_lines (
  unit            text NOT NULL,
  year            int  NOT NULL,
  n               int  NOT NULL,
  department      text,                    -- odbor; one has no name in the export
  paragraph       int,
  paragraph_name  text NOT NULL,
  item            int,
  item_name       text NOT NULL,
  approved        numeric(14,2) NOT NULL,
  revised         numeric(14,2) NOT NULL,
  actual          numeric(14,2) NOT NULL,
  PRIMARY KEY (unit, year, n)
);
CREATE INDEX IF NOT EXISTS budget_lines_paragraph ON budget_lines (unit, paragraph, year);
