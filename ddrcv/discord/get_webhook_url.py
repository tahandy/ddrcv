from discord_webhook import DiscordWebhook

_TEST_URL = "https://discord.com/api/webhooks/1297398877250392216/WHcu3y2-i2z9kY2L6nHGg5j3_q8xM42iuj37F1DfjCCZTsfG8Qt9RDSWJtZep6zfRZq7"

def _get_webhook_url():
    """
    Handle secret webhook url determination
    """
    # TODO: Actually determine it from ENV, don't just use the test URL
    return _TEST_URL

