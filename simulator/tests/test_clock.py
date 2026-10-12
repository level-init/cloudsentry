from datetime import datetime, timezone

from fastapi.testclient import TestClient

from simulator.main import create_app

_START = datetime(2026, 4, 1, tzinfo=timezone.utc)
_PLUS_SEVEN = datetime(2026, 4, 8, tzinfo=timezone.utc)


def test_advancing_seven_days_reveals_samples_and_costs() -> None:
    client = TestClient(create_app())
    assert _now(client) == _START
    hidden = client.get(
        "/resources/i-dev-062/metrics",
        params={
            "name": "cpu_percent",
            "start": "2026-04-01T00:00:00Z",
            "end": "2026-04-08T00:00:00Z",
        },
    )
    april_before = client.get("/resources/i-dev-062/costs", params={"year": 2026, "month": 4})

    advanced = client.post("/clock/advance", json={"days": 7})
    samples = client.get(
        "/resources/i-dev-062/metrics",
        params={
            "name": "cpu_percent",
            "start": "2026-04-01T00:00:00Z",
            "end": "2026-04-08T00:00:00Z",
        },
    )
    april = client.get("/resources/i-dev-062/costs", params={"year": 2026, "month": 4}).json()
    default_metrics = client.get(
        "/resources/i-dev-062/metrics",
        params={"name": "cpu_percent"},
    ).json()
    default_costs = client.get("/resources/i-dev-062/costs").json()

    assert advanced.status_code == 200
    assert _now(client) == _PLUS_SEVEN
    assert hidden.status_code == 400
    assert april_before.json()["lines"] == []
    assert samples.status_code == 200
    body = samples.json()
    assert len(body) == 7 * 24
    assert body[0]["timestamp"].startswith("2026-04-01T00:00:00")
    assert body[-1]["timestamp"].startswith("2026-04-07T23:00:00")
    assert [line["day"] for line in april["lines"]] == [f"2026-04-{day:02d}" for day in range(1, 8)]
    assert april["total_cents"] > 0
    assert april["total_cents"] == sum(line["amount_cents"] for line in april["lines"])
    assert len(default_metrics) == 24
    assert default_metrics[-1]["timestamp"].startswith("2026-04-07T23:00:00")
    assert default_costs["year"] == 2026
    assert default_costs["month"] == 4
    assert len(default_costs["lines"]) == 7


def test_the_same_advance_is_deterministic() -> None:
    first = TestClient(create_app())
    second = TestClient(create_app())
    assert (
        first.post("/clock/advance", json={"days": 7}).json()
        == second.post(
            "/clock/advance",
            json={"days": 7},
        ).json()
    )
    params = {
        "name": "cpu_percent",
        "start": "2026-04-01T00:00:00Z",
        "end": "2026-04-02T00:00:00Z",
    }
    assert (
        first.get("/resources/i-dev-062/metrics", params=params).json()
        == second.get(
            "/resources/i-dev-062/metrics",
            params=params,
        ).json()
    )
    costs = {"year": 2026, "month": 4}
    assert (
        first.get("/resources/i-dev-062/costs", params=costs).json()
        == second.get(
            "/resources/i-dev-062/costs",
            params=costs,
        ).json()
    )


def test_setting_the_clock_twice_is_idempotent() -> None:
    client = TestClient(create_app())
    client.post("/clock/advance", json={"days": 7})
    first = client.put("/clock", json={"now": "2026-04-01T00:00:00Z"})
    second = client.put("/clock", json={"now": "2026-04-01T00:00:00Z"})
    april = client.get("/resources/i-dev-062/costs", params={"year": 2026, "month": 4})

    assert first.status_code == 200
    assert second.json() == first.json()
    assert _parse(second.json()["now"]) == _START
    assert april.json()["lines"] == []
    assert client.post("/clock/advance", json={"days": 0}).status_code == 422
    assert client.put("/clock", json={"now": "2025-01-01T00:00:00Z"}).status_code == 400


def _now(client: TestClient) -> datetime:
    return _parse(client.get("/clock").json()["now"])


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
