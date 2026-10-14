"""Sample detector used to prove the batch runner.

It reports present resources tagged scenario=sample. Real waste detectors
replace this pattern; they are not part of the framework.
"""

from sqlalchemy.orm import Session

from app.proposals import Finding
from app.schemas import Resource


class SampleDetector:
    name = "sample"

    def detect(self, resources: list[Resource], session: Session | None = None) -> list[Finding]:
        return [
            Finding(
                finding_id=f"sample-{resource.resource_id}",
                resource_ids=[resource.resource_id],
                category="sample",
                summary=f"{resource.resource_id} is marked as a sample finding",
                evidence=[f"tag scenario=sample on {resource.resource_id}"],
            )
            for resource in resources
            if resource.present and resource.tags.get("scenario") == "sample"
        ]
