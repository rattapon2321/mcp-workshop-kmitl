// ============================================================
// Native vector index on device profiles (Neo4j 5.x)
//
// Why Neo4j needs vectors at all when pgvector and OpenSearch exist:
// this is the only store where a semantic hit can be followed by a
// graph traversal in the SAME query. "Find devices that look like an
// aggregation point for customer access, then show me what is under them"
// is one Cypher statement here and two round trips anywhere else.
//
// The workshop compares all three stores side by side - see
// instructions/day3/lab5-vector-store-comparison.md
//
// Vectors are written by docker/seeder/seed.py; this file only declares
// the index so the property has somewhere to live.
// ============================================================

CREATE VECTOR INDEX device_embedding IF NOT EXISTS
FOR (d:Device) ON (d.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }
};

CREATE VECTOR INDEX circuit_embedding IF NOT EXISTS
FOR (c:Circuit) ON (c.embedding)
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 768,
    `vector.similarity_function`: 'cosine'
  }
};

// Full-text index for the keyword-vs-semantic comparison in the lab.
CREATE FULLTEXT INDEX device_fulltext IF NOT EXISTS
FOR (d:Device) ON EACH [d.device_id, d.profile_text];
