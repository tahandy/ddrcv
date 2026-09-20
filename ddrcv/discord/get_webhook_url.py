"""Resolve the optional webhook used by legacy Discord examples."""
import os


def _get_webhook_url():
    """Require an operator-supplied webhook; never bundle a credential."""
    url = os.environ.get('DDRCV_DISCORD_WEBHOOK_URL', '').strip()
    if not url:
        raise ValueError('Set DDRCV_DISCORD_WEBHOOK_URL before using the legacy Discord helper')
    return url
