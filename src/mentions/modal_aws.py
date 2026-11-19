"""Use Modal's injected identity with the AWS SDK's renewable OIDC provider."""
import os
import tempfile
from pathlib import Path

_TOKEN_PATH = None


def configure_modal_oidc():
    """Configure only inside a Modal container; never accept forwarded AWS keys."""
    global _TOKEN_PATH
    token = os.environ.get('MODAL_IDENTITY_TOKEN')
    role = os.environ.get('AWS_ROLE_ARN')
    if not token or not role:
        raise RuntimeError('Modal identity and robotics-research-aws role configuration are required')
    if any(os.environ.get(name) for name in ('AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_PROFILE')):
        raise RuntimeError('Forwarded AWS credentials/profiles are not allowed in the Modal OIDC pipeline')
    if _TOKEN_PATH is None:
        fd, name = tempfile.mkstemp(prefix='modal-oidc-', suffix='.jwt')
        os.close(fd)
        _TOKEN_PATH = Path(name)
    # Container-local file only, never on a Volume. The SDK rereads it when
    # refreshing its in-memory AWS session; Modal issues the identity token.
    _TOKEN_PATH.write_text(token)
    _TOKEN_PATH.chmod(0o600)
    os.environ['AWS_WEB_IDENTITY_TOKEN_FILE'] = str(_TOKEN_PATH)
    os.environ['AWS_ROLE_SESSION_NAME'] = 'robotics-research-modal'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
    import boto3
    boto3.setup_default_session(region_name='us-east-1')
    credentials = boto3.DEFAULT_SESSION.get_credentials()
    if credentials is None or credentials.method != 'assume-role-with-web-identity':
        raise RuntimeError('AWS SDK did not select the web-identity credential provider')


def probe_access():
    """Prove identity plus a bounded requester-pays S3 read; expose no tokens."""
    import boto3
    from mentions.pdf_store import _client, BUCKET, MANIFEST_KEY
    identity = boto3.client('sts').get_caller_identity()
    response = _client().get_object(Bucket=BUCKET, Key=MANIFEST_KEY,
                                    Range='bytes=0-31', RequestPayer='requester')
    try:
        data = response['Body'].read()
        if len(data) != 32 or response['ResponseMetadata']['HTTPStatusCode'] != 206:
            raise RuntimeError('S3 did not return the bounded manifest read')
    finally:
        response['Body'].close()
    return {'role':identity['Arn'], 'bucket':BUCKET, 'key':MANIFEST_KEY, 'bytes_read':len(data),
            'credential_provider':'assume-role-with-web-identity'}
