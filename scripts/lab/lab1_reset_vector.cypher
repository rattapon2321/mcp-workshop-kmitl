// ============================================================
// Lab 1 reset (Neo4j side): remove vector indexes and properties
//
// Run with:  make lab1-reset
//
// After this, semantic device lookup fails until the participant has:
//   1. CREATE VECTOR INDEX ... OPTIONS { vector.dimensions: 768, ... }
//   2. generated a profile text per device
//   3. embedded it and written it back with SET d.embedding = $vec
// ============================================================

DROP INDEX device_embedding IF EXISTS;
DROP INDEX circuit_embedding IF EXISTS;

MATCH (d:Device)  REMOVE d.embedding;
MATCH (c:Circuit) REMOVE c.embedding;

// Confirm: expect 0.
MATCH (n) WHERE n.embedding IS NOT NULL RETURN count(n) AS nodes_with_embedding;
