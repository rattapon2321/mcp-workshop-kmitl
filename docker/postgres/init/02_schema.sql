-- ============================================================
-- Schema: IP-MPLS network operations (workshop scale)
--
-- Responsibility split across the three stores:
--   PostgreSQL  -> tickets, device configuration, circuits, customers
--   Neo4j       -> topology and adjacency relationships
--   OpenSearch  -> device logs and vector search over documents
--
-- Keep this file readable: the MCP server exposes it as a Resource
-- and the LLM reads it before planning any query.
-- ============================================================

-- ---------- Reference: sites and devices ----------

CREATE TABLE sites (
    site_code   VARCHAR(8)   PRIMARY KEY,      -- BKK, NBI
    name_th     TEXT         NOT NULL,
    name_en     TEXT         NOT NULL,
    region      TEXT         NOT NULL
);

COMMENT ON TABLE sites IS 'Physical locations. The workshop dataset covers BKK and NBI only.';

CREATE TABLE devices (
    device_id     VARCHAR(32) PRIMARY KEY,     -- e.g. APE-NBI-03
    site_code     VARCHAR(8)  NOT NULL REFERENCES sites(site_code),
    role          VARCHAR(8)  NOT NULL,        -- CR | PE | APE | LPE
    vendor        TEXT        NOT NULL,
    model         TEXT        NOT NULL,
    os_version    TEXT        NOT NULL,
    mgmt_ip       INET        NOT NULL,
    status        VARCHAR(16) NOT NULL DEFAULT 'active',
    installed_on  DATE        NOT NULL,
    CONSTRAINT devices_role_check CHECK (role IN ('CR', 'PE', 'APE', 'LPE'))
);

COMMENT ON COLUMN devices.role IS
    'CR=Core Router, PE=Provider Edge, APE=Aggregation PE, LPE=Local PE';

CREATE INDEX idx_devices_site ON devices(site_code);
CREATE INDEX idx_devices_role ON devices(role);

-- ---------- Interfaces and configuration ----------

CREATE TABLE interfaces (
    id            SERIAL      PRIMARY KEY,
    device_id     VARCHAR(32) NOT NULL REFERENCES devices(device_id),
    if_name       TEXT        NOT NULL,        -- e.g. Te0/0/1
    if_type       TEXT        NOT NULL,        -- uplink | downlink | peer | mgmt
    admin_status  VARCHAR(8)  NOT NULL DEFAULT 'up',
    oper_status   VARCHAR(8)  NOT NULL DEFAULT 'up',
    speed_mbps    INTEGER     NOT NULL,
    mtu           INTEGER     NOT NULL,        -- scenario S3 depends on this value
    description   TEXT,
    UNIQUE (device_id, if_name)
);

CREATE INDEX idx_interfaces_device ON interfaces(device_id);

CREATE TABLE device_configs (
    device_id       VARCHAR(32) PRIMARY KEY REFERENCES devices(device_id),
    isis_level      VARCHAR(8)  NOT NULL,
    isis_metric     INTEGER     NOT NULL,
    default_mtu     INTEGER     NOT NULL,
    snmp_location   TEXT,
    config_markdown TEXT        NOT NULL,      -- running config rendered as Markdown
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON COLUMN device_configs.config_markdown IS
    'Config stored as Markdown so it can be chunked and embedded directly (see the ingestion lab).';

-- ---------- Customers and circuits ----------

CREATE TABLE customers (
    customer_id  VARCHAR(16) PRIMARY KEY,
    name         TEXT        NOT NULL,
    segment      VARCHAR(16) NOT NULL,         -- Enterprise | SME | Government
    contact_email TEXT,
    CONSTRAINT customers_segment_check
        CHECK (segment IN ('Enterprise', 'SME', 'Government'))
);

CREATE TABLE circuits (
    circuit_id      VARCHAR(24) PRIMARY KEY,   -- e.g. CIR-25-00417
    customer_id     VARCHAR(16) NOT NULL REFERENCES customers(customer_id),
    device_id       VARCHAR(32) NOT NULL REFERENCES devices(device_id),
    if_name         TEXT        NOT NULL,
    service_type    VARCHAR(24) NOT NULL,      -- MPLS-VPN | Internet | Leased Line
    bandwidth_mbps  INTEGER     NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'active',
    activated_on    DATE        NOT NULL
);

CREATE INDEX idx_circuits_device ON circuits(device_id);
CREATE INDEX idx_circuits_customer ON circuits(customer_id);

-- ---------- Tickets ----------

CREATE TABLE ticket_categories (
    code        VARCHAR(24) PRIMARY KEY,
    name_th     TEXT NOT NULL,
    description TEXT NOT NULL
);

CREATE TABLE tickets (
    ticket_id    VARCHAR(24) PRIMARY KEY,      -- e.g. TK-25-00042
    category     VARCHAR(24) NOT NULL REFERENCES ticket_categories(code),
    severity     VARCHAR(16) NOT NULL,         -- low | medium | high | critical
    status       VARCHAR(16) NOT NULL,         -- open | in_progress | closed
    site_code    VARCHAR(8)  REFERENCES sites(site_code),
    device_id    VARCHAR(32) REFERENCES devices(device_id),
    circuit_id   VARCHAR(24) REFERENCES circuits(circuit_id),
    title        TEXT        NOT NULL,
    description  TEXT        NOT NULL,
    opened_at    TIMESTAMPTZ NOT NULL,
    closed_at    TIMESTAMPTZ,
    assignee     TEXT,
    resolution   TEXT,
    CONSTRAINT tickets_severity_check
        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT tickets_status_check
        CHECK (status IN ('open', 'in_progress', 'closed'))
);

-- The embedding column ships populated so the demo works out of the box.
-- Lab 1 removes it on purpose and asks participants to rebuild it:
--   make lab1-reset      -> drops the column and its index
--   (participant work)   -> ALTER TABLE / generate / backfill / CREATE INDEX
--   make embed-tickets   -> reference backfill if they get stuck
--
-- Dimension 768 matches EmbeddingGemma 300M, the same model used in production.
ALTER TABLE tickets ADD COLUMN embedding vector(768);

COMMENT ON COLUMN tickets.embedding IS
    'EmbeddingGemma 300M vector of title + description. Rebuilt by participants in Lab 1.';

CREATE INDEX idx_tickets_status   ON tickets(status);
CREATE INDEX idx_tickets_opened   ON tickets(opened_at DESC);
CREATE INDEX idx_tickets_device   ON tickets(device_id);
CREATE INDEX idx_tickets_site     ON tickets(site_code);
CREATE INDEX idx_tickets_severity ON tickets(severity);
-- Trigram index so participants can compare keyword search against semantic search.
CREATE INDEX idx_tickets_title_trgm ON tickets USING gin (title gin_trgm_ops);
-- HNSW index for cosine distance. Created empty here; the seeder backfills vectors.
CREATE INDEX idx_tickets_embedding ON tickets
    USING hnsw (embedding vector_cosine_ops);

CREATE TABLE ticket_messages (
    id         SERIAL      PRIMARY KEY,
    ticket_id  VARCHAR(24) NOT NULL REFERENCES tickets(ticket_id) ON DELETE CASCADE,
    author     TEXT        NOT NULL,
    author_role VARCHAR(16) NOT NULL,          -- customer | engineer | system
    message    TEXT        NOT NULL,           -- mixed Thai/English on purpose (Module 1)
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_ticket_messages_ticket ON ticket_messages(ticket_id);

-- ---------- Convenience view used by the MCP tools ----------

CREATE VIEW v_ticket_overview AS
SELECT
    t.ticket_id,
    t.category,
    t.severity,
    t.status,
    t.site_code,
    t.device_id,
    d.role        AS device_role,
    t.circuit_id,
    c.customer_id,
    cu.name       AS customer_name,
    cu.segment    AS customer_segment,
    c.service_type,
    t.title,
    t.opened_at,
    t.closed_at,
    t.assignee
FROM tickets t
LEFT JOIN devices  d  ON d.device_id  = t.device_id
LEFT JOIN circuits c  ON c.circuit_id = t.circuit_id
LEFT JOIN customers cu ON cu.customer_id = c.customer_id;

COMMENT ON VIEW v_ticket_overview IS
    'Flattened ticket view. Prefer this over manual joins when exposing data through MCP tools.';
