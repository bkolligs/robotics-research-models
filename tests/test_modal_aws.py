import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import boto3
except ImportError:
    boto3 = None
from mentions import modal_aws


@unittest.skipUnless(boto3, "Requires bulk dependency group")
class ModalOIDCTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {
            'AWS_ROLE_ARN': 'arn:aws:iam::123456789012:role/test',
            'MODAL_IDENTITY_TOKEN': 'test-identity-token',
            'AWS_CONFIG_FILE': str(Path(self.temp.name) / 'no-config'),
            'AWS_SHARED_CREDENTIALS_FILE': str(Path(self.temp.name) / 'no-credentials'),
            'AWS_EC2_METADATA_DISABLED': 'true',
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        token_path = Path(self.temp.name) / 'identity.jwt'
        token_path.touch(mode=0o600)
        self.token_patch = patch.object(modal_aws, '_TOKEN_PATH', token_path)
        self.token_patch.start()
        self.addCleanup(self.token_patch.stop)
        old_session = boto3.DEFAULT_SESSION
        self.addCleanup(setattr, boto3, 'DEFAULT_SESSION', old_session)

    def test_selects_renewable_provider_and_private_local_token(self):
        modal_aws.configure_modal_oidc()
        credentials = boto3.DEFAULT_SESSION.get_credentials()
        self.assertEqual(credentials.method, 'assume-role-with-web-identity')
        self.assertTrue(callable(credentials._refresh_using))
        path = Path(os.environ['AWS_WEB_IDENTITY_TOKEN_FILE'])
        self.assertEqual(path.read_text(), 'test-identity-token')
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        os.environ['MODAL_IDENTITY_TOKEN'] = 'replacement-token'
        modal_aws.configure_modal_oidc()
        self.assertEqual(path.read_text(), 'replacement-token')

    def test_rejects_forwarded_credentials_and_profiles(self):
        for name in ('AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'AWS_PROFILE'):
            with self.subTest(name=name), patch.dict(os.environ, {name: 'unexpected'}):
                with self.assertRaisesRegex(RuntimeError, 'Forwarded AWS'):
                    modal_aws.configure_modal_oidc()

    def test_requires_both_identity_and_role(self):
        for name in ('MODAL_IDENTITY_TOKEN', 'AWS_ROLE_ARN'):
            with self.subTest(name=name), patch.dict(os.environ, {name: ''}):
                with self.assertRaisesRegex(RuntimeError, 'Modal identity'):
                    modal_aws.configure_modal_oidc()
