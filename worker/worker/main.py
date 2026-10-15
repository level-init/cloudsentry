import logging
import sys

from worker.billing_ingest import ingest_billing
from worker.config import get_settings
from worker.detectors import DetectResult, detect
from worker.explain import save_explanations
from worker.inventory import ingest_inventory
from worker.knowledge_ingest import ingest_knowledge
from worker.metric_ingest import ingest_metrics
from worker.proposals import save_proposals
from worker.schedule import detect_scheduled


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    get_settings()
    logging.info("worker ok")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) == 1:
        run()
        return
    if sys.argv[1:] == ["ingest-inventory"]:
        counts = ingest_inventory()
        logging.info(
            "inventory ingest created=%s updated=%s total=%s absent=%s",
            counts.created,
            counts.updated,
            counts.total,
            counts.absent,
        )
        return
    if sys.argv[1:] == ["ingest-metrics"]:
        counts = ingest_metrics()
        logging.info(
            "metrics ingest created=%s updated=%s rollups=%s resources=%s",
            counts.created,
            counts.updated,
            counts.rollups,
            counts.resources_with_series,
        )
        return
    if sys.argv[1:] == ["ingest-billing"]:
        counts = ingest_billing()
        logging.info(
            "billing ingest created=%s updated=%s records=%s",
            counts.created,
            counts.updated,
            counts.records,
        )
        return
    if sys.argv[1:] == ["ingest-knowledge"]:
        counts = ingest_knowledge()
        logging.info(
            "knowledge ingest resources_created=%s resources_updated=%s resources_absent=%s "
            "dependencies_created=%s dependencies_updated=%s "
            "incidents_created=%s incidents_updated=%s",
            counts.resources_created,
            counts.resources_updated,
            counts.resources_absent,
            counts.dependencies_created,
            counts.dependencies_updated,
            counts.incidents_created,
            counts.incidents_updated,
        )
        return
    if sys.argv[1:] == ["detect"]:
        _log_findings(detect())
        return
    if sys.argv[1:] == ["detect-schedule"]:
        _log_findings(detect_scheduled())
        return
    if sys.argv[1:] == ["propose"]:
        result = save_proposals()
        for proposal in result.created:
            logging.info(
                "proposal %s category=%s action=%s",
                proposal.proposal_id,
                proposal.category,
                proposal.proposed_actions[0],
            )
        return
    if sys.argv[1:] == ["explain"]:
        for proposal in save_explanations():
            logging.info("narrative %s", proposal.proposal_id)
        return
    raise SystemExit(f"unknown command {sys.argv[1]}")


def _log_findings(result: DetectResult) -> None:
    for finding in result.findings:
        logging.info(
            "finding %s category=%s resources=%s evidence=%s",
            finding.finding_id,
            finding.category,
            ",".join(finding.resource_ids),
            len(finding.evidence),
        )


if __name__ == "__main__":
    main()
