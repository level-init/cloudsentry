# Terraform change artifacts

CloudSentry writes reviewable HCL under `changes/<proposal_id>/main.tf` when an approved proposal is queued for execution. Each file comments the proposal id and the plan action. These files are for review. CloudSentry does not run `terraform apply` against real AWS in v1.

`TERRAFORM_CHANGES_DIR` defaults to `terraform/changes`.
