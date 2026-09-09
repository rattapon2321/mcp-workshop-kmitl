-- ============================================================
-- Lab 1 reference solution (SQL side only)
--
-- Do not open this before attempting the lab. The Python half -
-- calling the embedding endpoint and backfilling - is the part that
-- actually teaches something; this file only shows the DDL.
--
-- Run with:  make lab1-solution
-- ============================================================

-- Step 1: add the column. 768 matches EmbeddingGemma 300M.
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS embedding vector(768);

-- Step 2: (Python) generate and backfill vectors - see scripts/embed_tickets.py

-- Step 3: index for approximate nearest neighbour search.
--
-- Why cosine and not L2: embedding models are trained so that semantic
-- similarity corresponds to angle, not magnitude. Using vector_l2_ops here
-- gives noticeably worse results with the same data.
--
-- Build the index AFTER backfilling: HNSW built on an empty table then
-- filled row by row is slower and gives a worse graph.
CREATE INDEX IF NOT EXISTS idx_tickets_embedding ON tickets
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Step 4: verify. Every ticket should have a vector.
SELECT
    count(*)                                    AS total_tickets,
    count(embedding)                            AS with_embedding,
    count(*) - count(embedding)                 AS missing
FROM tickets;

-- Step 5: try a semantic search (replace the literal with a real vector).
-- The <=> operator is cosine distance: smaller is more similar.
--
-- SELECT ticket_id, title, embedding <=> :query_vec AS distance
-- FROM tickets
-- ORDER BY embedding <=> :query_vec
-- LIMIT 5;
