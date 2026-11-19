-- Run as database owner against the temporary Render database only.
BEGIN;
CREATE SCHEMA orbtalus_demo;
CREATE TABLE orbtalus_demo.daily_usage (
    day date NOT NULL,
    bucket text NOT NULL,
    used integer NOT NULL CHECK (used > 0),
    PRIMARY KEY (day, bucket)
);
REVOKE ALL ON SCHEMA orbtalus_demo FROM PUBLIC;
GRANT USAGE ON SCHEMA orbtalus_demo TO orbtalus_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON orbtalus_demo.daily_usage TO orbtalus_runtime;
COMMIT;
