# Monthly mention trends

`.github/workflows/monthly.yml` refreshes the full-text mention corpus on the
first of each month at 12:30 UTC. It can also be started manually on `main`.
It harvests current metadata, resumes the persistent Modal pipeline, downloads
the validated database, rebuilds the mention analysis, commits the yearly
corpus and aggregate outputs, and dispatches the Pages workflow.

The daily workflow is manual only; its 14-day guard remains unchanged.
The monthly workflow does not rerun the separate LLM-assisted architecture,
LLM, or evaluation surveys. Those exports retain their existing coverage.
arXiv's bulk snapshot can lag publication, so the latest month may be incomplete.
Do not run another pipeline against the same Modal Volume concurrently.

## Authentication

GitHub repository Actions secrets:

- `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`: credentials for the `benkolligs`
  workspace containing the `robotics-research-papers` Volume.

GitHub repository Actions variable:

- `AWS_ROLE_ARN`: ARN of the AWS role described below. An ARN is not a secret.

AWS uses GitHub OIDC rather than saved AWS access keys. The existing launcher
forwards the temporary AWS credentials to Modal workers using ephemeral Modal
Secrets. The workflow requests a six-hour session, so the role's maximum session
duration must be at least 21,600 seconds. S3 requester-pays charges accrue to
this AWS account.

The workflow also requests an inline STS session policy limited to
`s3:GetObject` on `arn:aws:s3:::arxiv/pdf/*`. This restricts its temporary
credentials even if the role has broader identity policies attached.

For an isolated month test, dispatch with `-f test_month=2026-10`. The run
creates a separate test Volume in the same `benkolligs` workspace and uploads
analysis artifacts without committing the test corpus or publishing Pages.
Test Volumes remain available for inspection after the run.

## One-time AWS setup

An administrator with IAM permissions must perform these steps. Refresh a local
login first with `aws login --profile project_poweruser` if using that profile.

1. In IAM → Identity providers, add an OpenID Connect provider if it does not
   already exist. Provider URL: `https://token.actions.githubusercontent.com`.
   Audience: `sts.amazonaws.com`.
2. Create a role named `robotics-research-github-actions` with the following
   trust policy, replacing `ACCOUNT_ID` with the AWS account ID:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:bkolligs@29968424/robotics-research-models@1434797657:ref:refs/heads/main"
      }
    }
  }]
}
```

This repository uses GitHub's immutable subject format (verified through the
repository OIDC settings API), so keep the owner and repository IDs in `sub`.
The AWS account currently used for this project is `280337078600`.

3. Attach this inline permissions policy. The pipeline fetches known manifest
   and archive keys; it needs no bucket listing or write access:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::arxiv/pdf/*"
  }]
}
```

4. Set the role's maximum session duration to six hours.
5. Save its ARN as the repository variable:

```bash
gh variable set AWS_ROLE_ARN --repo bkolligs/robotics-research-models \
  --body arn:aws:iam::ACCOUNT_ID:role/robotics-research-github-actions
```

6. Once the workflow is merged to `main`, start and inspect a manual run:

```bash
gh workflow run monthly.yml --ref main
gh run list --workflow monthly.yml --limit 1
```

References: [GitHub OIDC with AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws),
[AWS credentials action](https://github.com/aws-actions/configure-aws-credentials),
[Modal GitHub Actions authentication](https://modal.com/docs/guide/useful-snippets).
