import logging
import argparse
from scraper import RemyParser
from utils import load_config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('remy_parser.log')
    ]
)


def main():
    """
    The main function that loads the configuration, initializes the parser,
    and starts processing the links in parallel.
    """
    # Set up argument parser
    parser = argparse.ArgumentParser(description='Scrape and process song data from a specified URL.')
    parser.add_argument('--config', type=str, default='configs/ddr_world.json', help='Path to the configuration file (default: config.json)')

    args = parser.parse_args()

    # Load configuration from the provided path
    config = load_config(args.config)
    remy_parser = RemyParser(config)
    list_items = remy_parser.scrape_song_list()

    # Process the links in parallel with rate limiting
    remy_parser.process_links_in_parallel(list_items)


if __name__ == '__main__':
    main()
