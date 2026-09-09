-- ============================================================
-- Lab 1 reset: remove the vector column so participants rebuild it
--
-- Run with:  make lab1-reset
--
-- After this script the tickets table has no embedding column and no
-- vector index. Semantic search will fail until the participant has:
--   1. ALTER TABLE tickets ADD COLUMN embedding vector(768);
--   2. generated embeddings from the internal embedding endpoint
--   3. backfilled every row
--   4. CREATE INDEX ... USING hnsw (embedding vector_cosine_ops);
--
-- The `vector` extension itself is NOT removed - installing extensions
-- usually requires superuser and is an infrastructure task, not a lab task.
-- ============================================================

DROP INDEX IF EXISTS idx_tickets_embedding;
ALTER TABLE tickets DROP COLUMN IF EXISTS embedding;

-- Confirm the reset. Expect zero rows.
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'tickets' AND column_name = 'embedding';
