# Demo scenarios

Named fixtures in the seeded company. Each id exists in the seed from `make seed-simulator`. The resource `name` and `scenario` tag match the fixture key.

These are the positive fixtures for the five MVP detectors, plus one spike-trap that veto tests must not rightsize.

| Fixture | Resource id | Name | Why it is here |
| --- | --- | --- | --- |
| Idle compute | `i-dev-062` | `idle-dev-vm` | Development `t3.medium` with a flat low CPU. |
| Always-on development | `i-dev-026` | `always-on-dev` | Development `m5.large` that stays up overnight and on weekends. |
| Oversized compute | `i-prd-013` | `oversized-prod` | Production `m5.xlarge` with a flat low CPU. Safe to rightsize. |
| Unattached disk | `vol-dev-042` | `unattached-disk` | Development 500 GB `gp3` volume. Nothing depends on it. |
| Expensive storage | `bucket-prd-022` | `expensive-bucket` | Production 5 TB standard bucket. |
| Expensive snapshot | `snap-dev-007` | `expensive-snapshot` | Development 1 TB snapshot. |
| Spike-trap | `i-prd-017` | `spike-trap-prod` | Production `m5.xlarge`. Average CPU stays near 7%, with a Wednesday 15:00 UTC peak near 100%. Do not rightsize. |

`i-prd-005` is a different production instance: it also looks idle, and it has incident `inc-prd-idle`. It is not one of these waste fixtures. Idle detection and one-step rightsizing still match it. The incident does not remove the finding.

`i-prd-017` must not be flagged as idle, rightsized, or scheduled. Its average looks low enough, and the Wednesday peak is the veto. Detection records a `rightsizing_veto` finding instead of a resize. Planning stores a `REJECTED` proposal whose action is `reject resize of i-prd-017 to m5.large`. It does not offer `m5.large` or the two-step drop to `t3.medium` as something that can be approved. The checks are `worker/tests/test_seeded_waste.py` and `worker/tests/test_veto.py`. Precision expectations for the rest of the seed are in `worker/README.md`.

From the repository root:

```bash
make simulator-scenarios
```
