from datetime import date, datetime, timezone

from worker.billing_ingest import _months_through, records_from_report


def test_daily_lines_become_one_day_cost_records() -> None:
    records = records_from_report(
        {
            "lines": [
                {
                    "resource_id": "i-dev-062",
                    "day": "2026-03-01",
                    "amount_cents": 452,
                    "currency": "USD",
                }
            ]
        }
    )

    assert len(records) == 1
    assert records[0].amount == 4.52
    assert records[0].period_start == datetime(2026, 3, 1, tzinfo=timezone.utc)
    assert records[0].period_end == datetime(2026, 3, 2, tzinfo=timezone.utc)


def test_billing_window_runs_through_the_last_observed_month() -> None:
    assert _months_through(date(2026, 3, 31)) == [
        (2025, 12),
        (2026, 1),
        (2026, 2),
        (2026, 3),
    ]
