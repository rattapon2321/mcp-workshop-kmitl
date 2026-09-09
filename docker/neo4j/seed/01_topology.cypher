// ============================================================
// Network topology for the workshop dataset.
//
// Neo4j owns relationships. Anything that is a "what connects to what"
// question belongs here; ticket history and configuration live in PostgreSQL.
//
// The single most important structure in this file:
//   LPE-NBI-11, LPE-NBI-12 and LPE-NBI-13 all uplink to APE-NBI-03.
// That shared upstream is what the agent must discover in scenario S1.
//
// This script is idempotent - it can be re-run safely.
// ============================================================

// ---------- Constraints ----------
CREATE CONSTRAINT site_code IF NOT EXISTS
    FOR (s:Site) REQUIRE s.code IS UNIQUE;
CREATE CONSTRAINT device_id IF NOT EXISTS
    FOR (d:Device) REQUIRE d.device_id IS UNIQUE;
CREATE CONSTRAINT circuit_id IF NOT EXISTS
    FOR (c:Circuit) REQUIRE c.circuit_id IS UNIQUE;
CREATE CONSTRAINT customer_id IF NOT EXISTS
    FOR (c:Customer) REQUIRE c.customer_id IS UNIQUE;

// ---------- Sites ----------
MERGE (bkk:Site {code: 'BKK'})
    SET bkk.name_th = 'กรุงเทพมหานคร', bkk.name_en = 'Bangkok', bkk.region = 'Central';
MERGE (nbi:Site {code: 'NBI'})
    SET nbi.name_th = 'นนทบุรี', nbi.name_en = 'Nonthaburi', nbi.region = 'Central';

// ---------- Devices ----------
UNWIND [
  {id: 'CR-BKK-01',  site: 'BKK', role: 'CR',  vendor: 'Cisco',  model: 'ASR-9010',  mgmt: '10.10.0.1'},
  {id: 'CR-BKK-02',  site: 'BKK', role: 'CR',  vendor: 'Cisco',  model: 'ASR-9010',  mgmt: '10.10.0.2'},
  {id: 'PE-BKK-02',  site: 'BKK', role: 'PE',  vendor: 'Huawei', model: 'NE40E-X8',  mgmt: '10.10.1.2'},
  {id: 'APE-BKK-05', site: 'BKK', role: 'APE', vendor: 'Huawei', model: 'NE40E-X3',  mgmt: '10.10.2.5'},
  {id: 'PE-NBI-01',  site: 'NBI', role: 'PE',  vendor: 'Cisco',  model: 'ASR-9006',  mgmt: '10.20.1.1'},
  {id: 'PE-NBI-04',  site: 'NBI', role: 'PE',  vendor: 'Cisco',  model: 'ASR-9006',  mgmt: '10.20.1.4'},
  {id: 'APE-NBI-03', site: 'NBI', role: 'APE', vendor: 'Huawei', model: 'NE40E-X3',  mgmt: '10.20.2.3'},
  {id: 'LPE-NBI-11', site: 'NBI', role: 'LPE', vendor: 'Huawei', model: 'NE20E-S2F', mgmt: '10.20.3.11'},
  {id: 'LPE-NBI-12', site: 'NBI', role: 'LPE', vendor: 'Huawei', model: 'NE20E-S2F', mgmt: '10.20.3.12'},
  {id: 'LPE-NBI-13', site: 'NBI', role: 'LPE', vendor: 'Huawei', model: 'NE20E-S2F', mgmt: '10.20.3.13'}
] AS row
MERGE (d:Device {device_id: row.id})
    SET d.role = row.role, d.vendor = row.vendor, d.model = row.model,
        d.mgmt_ip = row.mgmt, d.status = 'active'
WITH d, row
MATCH (s:Site {code: row.site})
MERGE (d)-[:LOCATED_AT]->(s);

// ---------- Interfaces ----------
UNWIND [
  {dev: 'CR-BKK-01',  name: 'Hu0/0/0/0', mtu: 9000, speed: 100000},
  {dev: 'CR-BKK-01',  name: 'Hu0/0/0/1', mtu: 9000, speed: 100000},
  {dev: 'CR-BKK-01',  name: 'Hu0/0/0/2', mtu: 9000, speed: 100000},
  {dev: 'CR-BKK-02',  name: 'Hu0/0/0/0', mtu: 9000, speed: 100000},
  {dev: 'CR-BKK-02',  name: 'Te0/0/3',   mtu: 9000, speed: 10000},
  {dev: 'PE-BKK-02',  name: 'Hu0/1/0/0', mtu: 9000, speed: 100000},
  {dev: 'PE-BKK-02',  name: 'Te0/1/0/1', mtu: 9000, speed: 10000},
  {dev: 'PE-BKK-02',  name: 'Te0/1/0/2', mtu: 9000, speed: 10000},
  {dev: 'APE-BKK-05', name: 'Te0/1/1',   mtu: 9000, speed: 10000},
  {dev: 'APE-BKK-05', name: 'Ge0/2/1',   mtu: 1500, speed: 1000},
  {dev: 'APE-BKK-05', name: 'Ge0/2/2',   mtu: 1500, speed: 1000},
  {dev: 'PE-NBI-01',  name: 'Hu0/0/0/0', mtu: 9000, speed: 100000},
  {dev: 'PE-NBI-01',  name: 'Te0/0/1',   mtu: 9000, speed: 10000},
  {dev: 'PE-NBI-01',  name: 'Te0/0/2',   mtu: 9000, speed: 10000},
  {dev: 'PE-NBI-04',  name: 'Te0/0/1',   mtu: 1500, speed: 10000},
  {dev: 'PE-NBI-04',  name: 'Te0/0/2',   mtu: 9000, speed: 10000},
  {dev: 'APE-NBI-03', name: 'Te0/1/2',   mtu: 9000, speed: 10000},
  {dev: 'APE-NBI-03', name: 'Ge0/2/1',   mtu: 1500, speed: 1000},
  {dev: 'APE-NBI-03', name: 'Ge0/2/2',   mtu: 1500, speed: 1000},
  {dev: 'APE-NBI-03', name: 'Ge0/2/3',   mtu: 1500, speed: 1000},
  {dev: 'LPE-NBI-11', name: 'Ge0/0/1',   mtu: 1500, speed: 1000},
  {dev: 'LPE-NBI-11', name: 'Ge0/0/2',   mtu: 1500, speed: 1000},
  {dev: 'LPE-NBI-11', name: 'Ge0/0/3',   mtu: 1500, speed: 1000},
  {dev: 'LPE-NBI-12', name: 'Ge0/0/1',   mtu: 1500, speed: 1000},
  {dev: 'LPE-NBI-12', name: 'Ge0/0/2',   mtu: 1500, speed: 1000},
  {dev: 'LPE-NBI-13', name: 'Ge0/0/1',   mtu: 1500, speed: 1000},
  {dev: 'LPE-NBI-13', name: 'Ge0/0/2',   mtu: 1500, speed: 1000},
  {dev: 'LPE-NBI-13', name: 'Ge0/0/3',   mtu: 1500, speed: 1000}
] AS row
MATCH (d:Device {device_id: row.dev})
MERGE (i:Interface {key: row.dev + ':' + row.name})
    SET i.if_name = row.name, i.mtu = row.mtu, i.speed_mbps = row.speed,
        i.device_id = row.dev, i.oper_status = 'up'
MERGE (d)-[:HAS_INTERFACE]->(i);

// ---------- Physical links ----------
// UPLINK_TO points from the subordinate device toward its aggregation point.
// This direction is what makes get_upstream_devices() a single hop query.
UNWIND [
  {from: 'LPE-NBI-11', to: 'APE-NBI-03', bw: 1000},
  {from: 'LPE-NBI-12', to: 'APE-NBI-03', bw: 1000},
  {from: 'LPE-NBI-13', to: 'APE-NBI-03', bw: 1000},
  {from: 'APE-NBI-03', to: 'PE-NBI-01',  bw: 10000},
  {from: 'PE-NBI-01',  to: 'CR-BKK-01',  bw: 100000},
  {from: 'APE-BKK-05', to: 'PE-BKK-02',  bw: 10000},
  {from: 'PE-BKK-02',  to: 'CR-BKK-01',  bw: 100000}
] AS row
MATCH (a:Device {device_id: row.from}), (b:Device {device_id: row.to})
MERGE (a)-[u:UPLINK_TO]->(b) SET u.bandwidth_mbps = row.bw, u.status = 'up'
MERGE (a)-[c1:CONNECTED_TO]->(b) SET c1.bandwidth_mbps = row.bw, c1.status = 'up'
MERGE (b)-[c2:CONNECTED_TO]->(a) SET c2.bandwidth_mbps = row.bw, c2.status = 'up';

// Core pair runs east-west, not an uplink relationship.
MATCH (a:Device {device_id: 'CR-BKK-01'}), (b:Device {device_id: 'CR-BKK-02'})
MERGE (a)-[r1:CONNECTED_TO]->(b) SET r1.bandwidth_mbps = 100000, r1.status = 'up'
MERGE (b)-[r2:CONNECTED_TO]->(a) SET r2.bandwidth_mbps = 100000, r2.status = 'up';

// PE-NBI-04 peers directly with CR-BKK-02 - this link crosses sites,
// which is why scenario S3 cannot be diagnosed by looking at NBI alone.
MATCH (a:Device {device_id: 'PE-NBI-04'}), (b:Device {device_id: 'CR-BKK-02'})
MERGE (a)-[r1:CONNECTED_TO]->(b) SET r1.bandwidth_mbps = 10000, r1.status = 'up'
MERGE (b)-[r2:CONNECTED_TO]->(a) SET r2.bandwidth_mbps = 10000, r2.status = 'up';

// ---------- ISIS adjacencies ----------
// Everything is Up except the PE-NBI-04 <-> CR-BKK-02 pair (scenario S3).
UNWIND [
  {a: 'PE-NBI-01',  b: 'CR-BKK-01', state: 'Up',   level: 'L2'},
  {a: 'PE-BKK-02',  b: 'CR-BKK-01', state: 'Up',   level: 'L2'},
  {a: 'CR-BKK-01',  b: 'CR-BKK-02', state: 'Up',   level: 'L2'},
  {a: 'APE-NBI-03', b: 'PE-NBI-01', state: 'Up',   level: 'L2'},
  {a: 'APE-BKK-05', b: 'PE-BKK-02', state: 'Up',   level: 'L2'},
  {a: 'PE-NBI-04',  b: 'CR-BKK-02', state: 'Down', level: 'L2'}
] AS row
MATCH (x:Device {device_id: row.a}), (y:Device {device_id: row.b})
MERGE (x)-[r1:ISIS_NEIGHBOR]->(y) SET r1.state = row.state, r1.level = row.level
MERGE (y)-[r2:ISIS_NEIGHBOR]->(x) SET r2.state = row.state, r2.level = row.level;

// ---------- CDP neighbours ----------
// Mirrors the physical links. Kept as a separate relationship type because
// production ingests CDP and ISIS from different collectors.
MATCH (a:Device)-[:CONNECTED_TO]->(b:Device)
MERGE (a)-[:CDP_NEIGHBOR]->(b);
