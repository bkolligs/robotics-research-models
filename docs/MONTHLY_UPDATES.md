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

Every production run refreshes the architecture survey, frontier-LLM mention/use
survey, baseline evaluations, execution-provenance verification, and lifecycle
curves before building the site. Publication fails if any plot's population
coverage disagrees with the current catalog.

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
The monthly Actions job downloads the completed export from Modal; all AWS
requests, including the bulk manifest download, run inside Modal.

## Authentication

GitHub repository Actions secrets:

- `TYPESAFE_API_KEY`: the existing Jev classifier key for survey refreshes.
- `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`: credentials for the `benkolligs`
  workspace containing the `robotics-research-papers` Volume.

Modal Secret `robotics-research-aws` in the `benkolligs` workspace's `main`
environment stores only `AWS_ROLE_ARN`, the nonsecret ARN of the role below.
GitHub needs no AWS variables, AWS access keys, or AWS OIDC permission.

The `archives` and `worker` functions exchange their injected
`MODAL_IDENTITY_TOKEN` for AWS credentials using the SDK's web-identity provider.
The token file stays in container-local temporary storage, never a Volume.
The SDK automatically renews AWS sessions; forwarded AWS keys are rejected.
Only these two functions receive the role configuration. S3 requester-pays
charges accrue to the role's AWS account.

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

An administrator with IAM permissions must perform these steps. Refresh the
administrator login with `aws login --profile project_admin` when needed.

1. In IAM → Identity providers, add provider URL `https://oidc.modal.com`
   with audience `oidc.modal.com` if it does not already exist.
2. Create role `robotics-research-modal` in account `280337078600` with this
   trust policy. It allows only the two AWS-reading functions of this app in
   `benkolligs` (`ac-zn2ejj8lZ29IIEz7DdespP`), environment `main`:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::280337078600:oidc-provider/oidc.modal.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {"oidc.modal.com:aud": "oidc.modal.com"},
      "StringLike": {
        "oidc.modal.com:sub": [
          "modal:workspace_id:ac-zn2ejj8lZ29IIEz7DdespP:environment_name:main:app_name:robotics-research-monthly:function_name:archives:container_id:*",
          "modal:workspace_id:ac-zn2ejj8lZ29IIEz7DdespP:environment_name:main:app_name:robotics-research-monthly:function_name:worker:container_id:*"
        ]
      }
    }
  }]
}
```

3. Attach only this inline permissions policy. Known manifest and archive
   keys need no bucket listing or write access:

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

4. Store the role configuration in Modal and check both functions:

```bash
uv run --no-sync modal secret create --profile benkolligs --env main \
  robotics-research-aws AWS_ROLE_ARN=arn:aws:iam::280337078600:role/robotics-research-modal
MENTIONS_MODAL_VOLUME=robotics-research-papers uv run --no-sync modal run \
  --profile benkolligs --env main scripts/modal_pipeline.py --check-auth
```

The check reads only 32 bytes of the arXiv manifest per function and reports
the assumed role, without modifying the corpus. The default one-hour AWS
session is renewed by the SDK as needed. Keep `MENTIONS_MODAL_APP` at
`robotics-research-monthly` to match the role trust.

5. After verifying Modal access, retire the old `robotics-research-github-actions`
   role and remove the GitHub `AWS_ROLE_ARN` variable. Leave shared identity
   providers in place for other applications.
6. Publish the workflow change and start an isolated run with
   `gh workflow run monthly.yml --ref main -f test_month=2026-10`.

References: [Modal OIDC](https://modal.com/docs/guide/oidc-integration),
[Boto3 web-identity credentials](https://docs.aws.amazon.com/boto3/latest/guide/credentials.html).

## Survey checkpoints

`robotics-research-surveys` in `benkolligs` retains the published pre-October
2026 summaries as an immutable baseline, with separate per-month evidence,
raw classifier responses, verification responses, and aggregate outputs.
Historical raw responses were not available locally, so historical decisions
are preserved through their published aggregates and evaluation paper rows;
they are not fabricated or reclassified. Each new month is classified once,
then retries reuse matching evidence fingerprints. Combining snapshots rejects
overlapping months or changed classification policies. Uncertain historical
release checks and recorded source audits retain their existing dispositions.

The TypeSafe key is injected into only the survey step and forwarded as an
ephemeral Modal Secret. It is not stored in source or the survey Volume.
All plot summaries share the cumulative catalog coverage, and lifecycle curves
are regenerated from the combined evaluation decisions and release registry.
