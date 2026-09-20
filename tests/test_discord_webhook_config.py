"""Legacy webhook configuration must never fall back to bundled credentials."""
import os
import unittest
from unittest.mock import patch

from ddrcv.discord.get_webhook_url import _get_webhook_url


class WebhookConfigTests(unittest.TestCase):
    def test_missing_or_blank_webhook_fails_without_sending(self):
        for environment in ({}, {'DDRCV_DISCORD_WEBHOOK_URL': '  '}):
            with self.subTest(environment=environment):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(ValueError, 'DDRCV_DISCORD_WEBHOOK_URL'):
                        _get_webhook_url()

    def test_explicit_environment_webhook_is_used(self):
        url = 'https://discord.com/api/webhooks/123/example-token'
        with patch.dict(os.environ, {'DDRCV_DISCORD_WEBHOOK_URL': f' {url} '}):
            self.assertEqual(_get_webhook_url(), url)


if __name__ == '__main__':
    unittest.main()
