-- ============================================================
-- Extensions
--
-- NOTE FOR THE WORKSHOP:
-- The `vector` extension is installed here, but NO embedding column
-- is created anywhere in the schema. Participants add it themselves
-- in Lab 1 (day1/lab1-add-vector-column.md) so they experience the
-- full path: ALTER TABLE -> generate embeddings -> backfill -> index.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- trigram search, used to contrast with semantic search
