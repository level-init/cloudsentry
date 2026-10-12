from fastapi.testclient import TestClient

from simulator.main import create_app


def test_openapi_lists_read_paths() -> None:
    schema = create_app().openapi()
    paths = set(schema["paths"])

    assert {
        "/health",
        "/clock",
        "/clock/advance",
        "/resources",
        "/resources/{resource_id}",
        "/resources/{resource_id}/tags",
        "/resources/{resource_id}/metrics",
        "/resources/{resource_id}/costs",
        "/resources/{resource_id}/dependencies",
        "/resources/{resource_id}/dependents",
        "/resources/{resource_id}/incidents",
    } <= paths


def test_inventory_page_returns_the_full_company() -> None:
    client = TestClient(create_app())
    response = client.get("/resources")
    body = response.json()

    assert response.status_code == 200
    assert body["total"] == 180
    assert len(body["items"]) == 180
    assert {item["environment"] for item in body["items"]} == {
        "development",
        "staging",
        "production",
    }


def test_filters_and_resource_reads() -> None:
    client = TestClient(create_app())
    production = client.get("/resources", params={"environment": "production"}).json()
    spike = client.get("/resources", params={"scenario": "spike_trap"}).json()
    tags = client.get("/resources/i-prd-017/tags")
    metrics = client.get("/resources/i-prd-017/metrics", params={"name": "cpu_percent"})
    costs = client.get("/resources/i-prd-017/costs")
    dependencies = client.get("/resources/i-prd-000/dependencies")
    incidents = client.get("/resources/i-prd-005/incidents")
    missing = client.get("/resources/i-missing")

    assert production["total"] == 60
    assert [item["resource_id"] for item in spike["items"]] == ["i-prd-017"]
    assert tags.json()["scenario"] == "spike_trap"
    assert metrics.status_code == 200
    assert len(metrics.json()) == 24
    cost_body = costs.json()
    assert cost_body["total_cents"] == sum(line["amount_cents"] for line in cost_body["lines"])
    assert dependencies.json()[0]["relationship"] == "uses_database"
    assert incidents.json()[0]["incident_id"] == "inc-prd-idle"
    assert missing.status_code == 404
