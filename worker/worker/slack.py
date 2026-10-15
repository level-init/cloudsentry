"""Optional Slack webhook stub.

SLACK_WEBHOOK_ENABLED defaults to false. While it is false, nothing is sent.
While it is true, the stub logs the proposal id and does not call Slack.
"""

import logging


def notify_slack(proposal_id: str, *, enabled: bool) -> None:
    if not enabled:
        return
    logging.info("slack webhook stub proposal_id=%s", proposal_id)
