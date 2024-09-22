import json
import logging
import sys
from pathlib import Path

def sanitize_filename(text):
    """
    Sanitize a string to create a valid filename.

    :param text: The string to sanitize.
    :return: The sanitized string.
    """
    return "".join(c if c.isalnum() else "_" for c in text)

def load_config(config_file='config.json'):
    """
    Load configuration from a JSON file.

    :param config_file: The path to the configuration file (default is 'config.json').
    :return: A dictionary containing the configuration.
    """
    try:
        config_path = Path(config_file)
        with config_path.open('r') as f:
            config = json.load(f)
        logging.info(f'Loaded configuration from {config_file}')
        return config
    except (OSError, json.JSONDecodeError) as e:
        logging.error(f'Error loading configuration file: {e}')
        sys.exit(1)
