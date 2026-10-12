from worker.metric_ingest import daily_rollups


def test_daily_rollups_keep_average_and_peak() -> None:
    samples = [
        {
            "name": "cpu_percent",
            "timestamp": "2026-03-02T00:00:00Z",
            "value": 4.0,
            "unit": "percent",
        },
        {
            "name": "cpu_percent",
            "timestamp": "2026-03-02T01:00:00Z",
            "value": 8.0,
            "unit": "percent",
        },
        {
            "name": "cpu_percent",
            "timestamp": "2026-03-03T15:00:00Z",
            "value": 10.0,
            "unit": "percent",
        },
    ]

    rollups = daily_rollups("i-dev-062", samples)
    summary = [(rollup.day.isoformat(), rollup.avg_value, rollup.peak_value) for rollup in rollups]

    assert summary == [
        ("2026-03-02", 6.0, 8.0),
        ("2026-03-03", 10.0, 10.0),
    ]
    assert rollups[0].unit == "percent"
