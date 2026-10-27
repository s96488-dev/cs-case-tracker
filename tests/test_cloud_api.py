import pytest
from fastapi.testclient import TestClient

from cloud import config, server
from cloud.buffer import Buffer
from common.models import Case, PriceTick


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "API_TOKEN", "secret")
    monkeypatch.setattr(server, "buf", Buffer(tmp_path / "b.db"))
    return TestClient(server.app)   # no lifespan: the collector does not start


def test_health_needs_no_token(client):
    assert client.get("/health").json()["ok"] is True


@pytest.mark.parametrize("path", ["/api/stats", "/api/ticks", "/api/sales", "/api/item_days"])
def test_data_endpoints_need_token(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_pull_and_ack(client):
    server.buf.save([PriceTick("A Case", 60, 100, 3)], [Case("A Case")])
    auth = {"Authorization": "Bearer secret"}
    batch = client.get("/api/ticks", headers=auth).json()
    assert batch["ticks"][0]["price_cents"] == 100
    assert client.post("/api/ack", json={"up_to_id": batch["max_id"]}, headers=auth).json() == {"ok": True}
    assert client.get("/api/stats", headers=auth).json()["pending_ticks"] == 0
