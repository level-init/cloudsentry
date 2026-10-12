from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from simulator.billing import SCHEDULED_WEEK_HOURS, WEEK_HOURS
from simulator.main import create_app

_BUSY = datetime(2026, 3, 18, 15, tzinfo=timezone.utc)
_QUIET = datetime(2026, 3, 22, 3, tzinfo=timezone.utc)


def test_stopping_idle_compute_zeros_cost_and_metrics() -> None:
    client = TestClient(create_app())
    before_cost = client.get("/resources/i-dev-062/costs").json()
    before_cpu = _cpu(client, "i-dev-062", _BUSY)

    stopped = client.post("/resources/i-dev-062/actions/stop")
    after_cost = client.get("/resources/i-dev-062/costs").json()
    again = client.get("/resources/i-dev-062/costs").json()
    after_cpu = _cpu(client, "i-dev-062", _BUSY)

    assert stopped.status_code == 200
    assert before_cost["total_cents"] > 0
    assert before_cpu > 0
    assert after_cost["total_cents"] == 0
    assert after_cost["lines"]
    assert all(line["amount_cents"] == 0 for line in after_cost["lines"])
    assert again == after_cost
    assert after_cpu == 0.0

    assert client.post(f"/actions/{stopped.json()['action_id']}/rollback").status_code == 200
    restored = client.get("/resources/i-dev-062/costs").json()
    assert restored["total_cents"] == before_cost["total_cents"]
    assert _cpu(client, "i-dev-062", _BUSY) == before_cpu


def test_rightsizing_changes_the_cost_trajectory_only() -> None:
    client = TestClient(create_app())
    before = client.get("/resources/i-prd-013/costs").json()
    before_cpu = _cpu(client, "i-prd-013", _BUSY)

    resized = client.post("/resources/i-prd-013/actions/resize", json={"sku": "m5.large"})
    after = client.get("/resources/i-prd-013/costs").json()

    assert resized.status_code == 200
    assert before["total_cents"] == 14016
    assert after["total_cents"] == 7008
    assert len(after["lines"]) == len(before["lines"])
    assert all(
        later["amount_cents"] < earlier["amount_cents"]
        for earlier, later in zip(before["lines"], after["lines"], strict=True)
    )
    assert _cpu(client, "i-prd-013", _BUSY) == before_cpu

    assert client.post(f"/actions/{resized.json()['action_id']}/rollback").status_code == 200
    assert client.get("/resources/i-prd-013/costs").json()["total_cents"] == before["total_cents"]


def test_weekday_schedule_cuts_cost_and_off_hours_metrics() -> None:
    client = TestClient(create_app())
    before = client.get("/resources/i-dev-026/costs").json()["total_cents"]
    busy_before = _cpu(client, "i-dev-026", _BUSY)

    scheduled = client.post(
        "/resources/i-dev-026/actions/schedule",
        json={"schedule": "weekdays-09-17"},
    )
    after = client.get("/resources/i-dev-026/costs").json()["total_cents"]

    assert scheduled.status_code == 200
    assert after == before * SCHEDULED_WEEK_HOURS // WEEK_HOURS
    assert after < before
    assert _cpu(client, "i-dev-026", _BUSY) == busy_before
    assert _cpu(client, "i-dev-026", _QUIET) == 0.0


def test_infrequent_access_halves_storage_cost() -> None:
    client = TestClient(create_app())
    before = client.get("/resources/bucket-prd-022/costs").json()["total_cents"]
    changed = client.post(
        "/resources/bucket-prd-022/actions/storage-lifecycle",
        json={"storage_class": "infrequent_access"},
    )
    after = client.get("/resources/bucket-prd-022/costs").json()["total_cents"]

    assert changed.status_code == 200
    assert before > 0
    assert after == before // 2


def _cpu(client: TestClient, resource_id: str, start: datetime) -> float:
    response = client.get(
        f"/resources/{resource_id}/metrics",
        params={
            "name": "cpu_percent",
            "start": start.isoformat(),
            "end": (start + timedelta(hours=1)).isoformat(),
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    return body[0]["value"]
