# Terraform change artifacts

When an approved proposal is queued for execution, CloudSentry writes a reviewable change under a fake repo path:

```text
terraform/changes/<proposal_id>/<hash12>/
  main.tf
  commit.json
```

- `main.tf` is the generated HCL. Each block comments the proposal id and the plan action.
- `commit.json` is commit-like metadata: full content `hash`, `created_at`, `proposal_id`, `files`, and `review_path`.
- The short `<hash12>` directory is the first 12 characters of the SHA-256 of `main.tf`.

## How to review

1. Approve a proposal: `POST /proposals/{id}/approve` with `X-Actor` and a reason.
2. Queue it: `POST /proposals/{id}/execute` with `X-Actor`.
3. Read the run: `GET /executions/execution-{id}`.
4. Open `artifact_path` on disk. That directory is the review path. `ls` it and read `main.tf`.

`GET /executions/{id}` returns `artifact_path`, `artifact_hash`, and `artifact_created_at`.

`TERRAFORM_CHANGES_DIR` defaults to `terraform/changes`. CloudSentry does not run `terraform apply` and does not open a real GitHub pull request in this phase.
