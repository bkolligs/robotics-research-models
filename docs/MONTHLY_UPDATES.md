# Monthly mention trends

`.github/workflows/monthly.yml` refreshes the full-text mention corpus on the
first of each month at 12:30 UTC, targeting the previous UTC calendar month
(e.g. December 1 catalogs November). It can also be started manually on `main`.
It synchronizes cached OAI-PMH metadata, resumes the persistent Modal pipeline, downloads
the validated database, rebuilds the mention analysis, commits the yearly
corpus and aggregate outputs, and dispatches the Pages workflow. Each monthly
scan uses `robotics-research-month-YYYY-MM`; the cumulative analysis database
is `catalog.sqlite` in `robotics-research-papers`. Month merges preserve other
months and refuse to discard previously scanned papers. The catalog records
the source Modal Volume for each paper in `catalog_sources`; PDF/text paths
are relative to that source Volume, not to the catalog storage Volume.
The original historical `papers.sqlite` remains the bootstrap snapshot.

The monthly workflow does not rerun the separate LLM-assisted architecture,
LLM, or evaluation surveys. Those exports retain their existing coverage.
arXiv's bulk snapshot can lag publication, so the latest month may be incomplete.
Do not run another pipeline against the same Modal Volume concurrently.

## Metadata cache

The recommended [arXiv OAI-PMH feed](https://info.arxiv.org/help/oa/index.html)
at `https://oaipmh.arxiv.org/oai` replaces search-API pagination.
`scripts/modal_harvest.py` keeps `oai.sqlite` in the separate
`robotics-research-metadata` Modal Volume in `benkolligs`.
The first run copies the complete `cs:cs:RO` set using `arXivRaw`; subsequent
runs request changes since the previous completed harvest's server date.
OAI datestamps are modification dates, so October selection uses the original
v1 submission date from version history, after synchronization completes.

Each page and continuation token are committed together in SQLite and persisted
to the Volume. Expired tokens restart from the previous completed watermark;
replayed records are idempotent. Failed or page-limited harvests do not export
partial metadata or start PDF processing. Legacy `harvest_cursor.txt` files are
ignored; existing search-API records do not establish an OAI synchronization
watermark. A cold cache requires one complete subject harvest.

For local use, `uv run mentions-harvest` maintains `data/oai.sqlite` and exports
study records to `data/records.jsonl`. `--month YYYY-MM` filters the export only.
The monthly Actions job downloads the completed export from Modal and obtains
AWS credentials afterward, preserving their lifetime for PDF processing.

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

To publish or retry a specific production month, dispatch with `-f month=2026-10`.
This is useful when arXiv's approximately monthly bulk release is not yet
available on the first. Do not set both `month` and `test_month`. October 2026
was promoted from the validated test Volume `robotics-research-test-44467441721`;
retain that Volume because the production catalog references its PDF/text files.

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
