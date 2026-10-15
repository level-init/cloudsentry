import logging

import pytest

from worker.config import get_settings
from worker.slack import notify_slack


def test_slack_webhook_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SLACK_WEBHOOK_ENABLED", "false")

    assert get_settings().slack_webhook_enabled is False


def test_slack_stub_logs_only_when_enabled(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        notify_slack("opt-h5", enabled=False)

    assert "slack webhook stub" not in caplog.text

    with caplog.at_level(logging.INFO):
        notify_slack("opt-h5", enabled=True)

    assert "slack webhook stub proposal_id=opt-h5" in caplog.text
