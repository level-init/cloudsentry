from fastapi.testclient import TestClient

from simulator.main import create_app


def test_schedule_rollback_restores_the_prior_value() -> None:
    client = TestClient(create_app())
    before = client.get("/resources/i-dev-026").json()
    applied = client.post(
        "/resources/i-dev-026/actions/schedule",
        json={"schedule": "weekdays-09-17"},
    )
    during = client.get("/resources/i-dev-026").json()
    restored = client.post(f"/actions/{applied.json()['action_id']}/rollback")
    after = client.get("/resources/i-dev-026").json()

    assert before["schedule"] == "always_on"
    assert applied.status_code == 200
    assert during["schedule"] == "weekdays-09-17"
    assert restored.status_code == 200
    assert after["schedule"] == before["schedule"]


def test_each_mvp_action_applies_and_rolls_back() -> None:
    client = TestClient(create_app())

    stopped = client.post("/resources/i-dev-062/actions/stop")
    assert stopped.status_code == 200
    assert client.get("/resources/i-dev-062").json()["power_state"] == "stopped"
    assert client.post(f"/actions/{stopped.json()['action_id']}/rollback").status_code == 200
    assert client.get("/resources/i-dev-062").json()["power_state"] == "running"

    resized = client.post("/resources/i-prd-013/actions/resize", json={"sku": "m5.large"})
    assert resized.status_code == 200
    assert client.get("/resources/i-prd-013").json()["sku"] == "m5.large"
    assert client.get("/resources/i-prd-013/costs").json()["total_cents"] == 7008
    assert client.post(f"/actions/{resized.json()['action_id']}/rollback").status_code == 200
    assert client.get("/resources/i-prd-013").json()["sku"] == "m5.xlarge"

    removed = client.post("/resources/vol-dev-042/actions/delete-unattached")
    assert removed.status_code == 200
    assert client.get("/resources/vol-dev-042").status_code == 404
    assert client.post(f"/actions/{removed.json()['action_id']}/rollback").status_code == 200
    assert client.get("/resources/vol-dev-042").status_code == 200

    changed = client.post(
        "/resources/bucket-prd-022/actions/storage-lifecycle",
        json={"storage_class": "infrequent_access"},
    )
    assert changed.status_code == 200
    assert client.get("/resources/bucket-prd-022").json()["storage_class"] == "infrequent_access"
    assert client.post(f"/actions/{changed.json()['action_id']}/rollback").status_code == 200
    assert client.get("/resources/bucket-prd-022").json()["storage_class"] == "standard"


def test_illegal_mutations_are_rejected() -> None:
    client = TestClient(create_app())

    assert client.post("/resources/vol-dev-042/actions/stop").status_code == 400
    assert client.post("/resources/i-dev-062/actions/start").status_code == 400
    scheduled = client.post(
        "/resources/i-prd-013/actions/schedule",
        json={"schedule": "weekdays-09-17"},
    )
    assert scheduled.status_code == 400
    assert client.post("/resources/vol-prd-003/actions/delete-unattached").status_code == 400
    assert (
        client.post(
            "/resources/i-prd-017/actions/storage-lifecycle",
            json={"storage_class": "infrequent_access"},
        ).status_code
        == 400
    )
    assert client.post("/actions/act-missing/rollback").status_code == 404
