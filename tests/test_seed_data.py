"""Verify the dataset supports every scenario in data/scenarios.md.

If one of these fails, a challenge somewhere has become unanswerable.
"""

from __future__ import annotations

import os

import pytest
from conftest import needs_neo4j, needs_opensearch, needs_postgres

PG_DSN = os.getenv("PG_ADMIN_DSN",
                   "postgresql://mpls:mpls_dev_password@localhost:5432/mplsdb")


@needs_postgres
class TestPostgres:
    @pytest.fixture
    def conn(self):
        import psycopg

        with psycopg.connect(PG_DSN) as connection:
            yield connection

    def test_ten_devices_two_sites(self, conn):
        assert conn.execute("SELECT count(*) FROM devices").fetchone()[0] == 10
        assert conn.execute("SELECT count(*) FROM sites").fetchone()[0] == 2

    def test_s3_mtu_mismatch_exists(self, conn):
        """Scenario S3 is only diagnosable if the mismatch is actually present."""
        local = conn.execute(
            "SELECT mtu FROM interfaces WHERE device_id='PE-NBI-04' AND if_name='Te0/0/1'"
        ).fetchone()[0]
        peer = conn.execute(
            "SELECT mtu FROM interfaces WHERE device_id='CR-BKK-02' AND if_name='Te0/0/3'"
        ).fetchone()[0]
        assert local == 1500 and peer == 9000, "S3 requires an MTU mismatch"

    def test_s2_device_has_no_tickets(self, conn):
        """The whole point of S2 is a degrading device nobody has reported."""
        count = conn.execute(
            "SELECT count(*) FROM tickets WHERE device_id='PE-BKK-02'"
        ).fetchone()[0]
        assert count == 0

    def test_s1_tickets_span_three_lpes(self, conn):
        count = conn.execute(
            """SELECT count(DISTINCT device_id) FROM tickets
               WHERE device_id LIKE 'LPE-NBI-1%' AND category='intermittent'"""
        ).fetchone()[0]
        assert count == 3

    def test_s4_maintenance_ticket_exists(self, conn):
        count = conn.execute(
            """SELECT count(*) FROM tickets
               WHERE device_id='APE-BKK-05' AND category='maintenance'"""
        ).fetchone()[0]
        assert count >= 1

    def test_readonly_role_cannot_write(self):
        import psycopg

        dsn = ("host=localhost dbname=mplsdb user=mcp_reader "
               "password=mcp_reader_password")
        with psycopg.connect(dsn) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("UPDATE tickets SET severity='low' WHERE false")


@needs_neo4j
class TestNeo4j:
    @pytest.fixture
    def session(self):
        from neo4j import GraphDatabase

        driver = GraphDatabase.driver(
            "bolt://localhost:7687", auth=("neo4j", "neo4j_dev_password")
        )
        with driver, driver.session() as s:
            yield s

    def test_s1_shared_upstream(self, session):
        """Three LPEs must share one APE, or Q21 has no answer."""
        count = session.run(
            """MATCH (l:Device)-[:UPLINK_TO]->(:Device {device_id:'APE-NBI-03'})
               RETURN count(l) AS n"""
        ).single()["n"]
        assert count == 3

    def test_s3_adjacency_down(self, session):
        count = session.run(
            """MATCH (:Device {device_id:'PE-NBI-04'})
                     -[r:ISIS_NEIGHBOR {state:'Down'}]->
                     (:Device {device_id:'CR-BKK-02'})
               RETURN count(r) AS n"""
        ).single()["n"]
        assert count == 1

    def test_cross_site_path_exists(self, session):
        count = session.run(
            """MATCH p = (:Device {device_id:'LPE-NBI-11'})-[:UPLINK_TO*1..4]->
                         (:Device {device_id:'CR-BKK-01'})
               RETURN count(p) AS n"""
        ).single()["n"]
        assert count >= 1


@needs_opensearch
class TestOpenSearch:
    @pytest.fixture
    def client(self):
        from opensearchpy import OpenSearch

        return OpenSearch(hosts=["http://localhost:9200"])

    def test_log_volume(self, client):
        assert client.count(index="network-logs-*")["count"] >= 1800

    @pytest.mark.parametrize("scenario,minimum",
                             [("S1", 300), ("S2", 250), ("S3", 150), ("S4", 140)])
    def test_scenario_logs_present(self, client, scenario, minimum):
        count = client.count(
            index="network-logs-*", body={"query": {"term": {"scenario": scenario}}}
        )["count"]
        assert count >= minimum

    def test_flap_is_on_the_right_device(self, client):
        count = client.count(
            index="network-logs-*",
            body={"query": {"bool": {"must": [
                {"term": {"device_id": "APE-NBI-03"}},
                {"term": {"event_type": "LINK-UPDOWN"}}]}}},
        )["count"]
        assert count >= 60, "S1 needs ~40 down + ~40 up events"

    def test_docs_have_vector_mapping(self, client):
        mapping = client.indices.get_mapping(index="network-docs")
        assert any("embedding" in m["mappings"]["properties"] for m in mapping.values())
