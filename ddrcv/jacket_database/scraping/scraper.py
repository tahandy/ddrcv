import json
import time

import requests
import logging
import concurrent.futures
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, unquote
from pathlib import Path
from utils import sanitize_filename
from token_bucket import TokenBucket


class RemyParser:
    """
    RemyParser is responsible for scraping song data from a specified URL,
    downloading images, and saving the metadata to disk.
    """
    def __init__(self, config):
        """
        Initialize the RemyParser with a configuration.

        :param config: A dictionary containing configuration options.
        """
        self.url = config.get('url')
        self.output_dir = Path(config.get('output_dir'))
        self.bucket = TokenBucket(rate=config.get('rate_limit', 5), capacity=config.get('rate_limit', 5))
        self.delay = config.get('delay', 1.0)
        self.max_workers = config.get('max_workers', 5)
        self.soup = None
        self.load_page()
        self.ensure_output_directory()

    def load_page(self):
        """
        Load the webpage at the specified URL and parse it with BeautifulSoup.
        """
        try:
            response = requests.get(self.url)
            response.raise_for_status()  # Raises an error for bad status codes
            self.soup = BeautifulSoup(response.content, 'html.parser')
            logging.info(f'Successfully loaded the page: {self.url}')
        except requests.exceptions.RequestException as e:
            logging.error(f'Error fetching the page: {e}')
            self.soup = None

    def ensure_output_directory(self):
        """
        Ensure the output directory exists. If it doesn't, create it.
        """
        try:
            if not self.output_dir.exists():
                self.output_dir.mkdir(parents=True, exist_ok=True)
            logging.info(f'Output directory is ready: {self.output_dir}')
        except OSError as e:
            logging.error(f'Error creating output directory: {e}')
            raise e

    def scrape_song_list(self):
        """
        Scrape the list of songs from the main page. Extracts the first <a> link from each <li> within <ul> elements.

        :return: A list of tuples containing the full URL and the relative URL for each song.
        """
        if not self.soup:
            logging.error('Error: Soup object not initialized.')
            return []

        parser_output_div = self.soup.find('div', class_='mw-parser-output')

        if not parser_output_div:
            logging.error('Error: No div with class "mw-parser-output" found on the page.')
            return []

        list_items = []
        ul_elements = parser_output_div.find_all('ul', recursive=False)

        for ul in ul_elements:
            for li in ul.find_all('li'):
                # Get the first <a> link in the <li>
                first_link = li.find('a', href=True)
                if first_link:
                    # Convert relative URLs to absolute URLs
                    full_url = urljoin(self.url, first_link['href'])
                    list_items.append((full_url, first_link['href'][1:]))

        logging.info(f'Found {len(list_items)} songs to process.')
        return list_items

    def is_song_processed(self, song_dir):
        """
        Check if a song has already been processed by verifying the presence of PNG files and JSON metadata.

        :param song_dir: The directory where the song's data should be stored.
        :return: True if the song has been processed, False otherwise.
        """
        try:
            # Check for PNG files in the directory
            png_files = list(song_dir.glob('*.png')) + list(song_dir.glob('*.PNG'))
            if not png_files:
                return False

            # Check if JSON file exists and is valid
            json_path = song_dir / 'metadata.json'
            if not json_path.exists():
                return False

            with json_path.open('r') as f:
                metadata = json.load(f)

            # Ensure all fields in the metadata are not None
            required_fields = ['Song', 'Artist', 'BPM', 'Length', 'Table']
            if all(metadata.get(field) is not None for field in required_fields):
                return True

        except (OSError, json.JSONDecodeError) as e:
            logging.error(f'Error checking song metadata in {song_dir}: {e}')
            return False

        return False

    def process_song(self, link_data):
        """
        Process a song by scraping its metadata, downloading its images, and saving the results.

        :param link_data: A tuple containing the full URL and relative URL for the song.
        """
        link, list_item_text = link_data
        song_dir = self.output_dir / sanitize_filename(list_item_text)

        # Check if the song has already been processed
        if self.is_song_processed(song_dir):
            logging.info(f"Skipping already processed song: {list_item_text}")
            return

        # Rate limiting with token bucket
        while not self.bucket.consume():
            time.sleep(0.1)  # Wait briefly until a token is available

        try:
            response = requests.get(link)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Extract the mw-parser-output div content
            content_div = soup.find('div', class_='mw-parser-output')
            if not content_div:
                logging.error(f'No "mw-parser-output" div found in {link}')
                return

            # Parse the song title using extract_song method
            song = self.extract_song(content_div)

            # Identify the "song information" paragraph for other fields
            song_info_paragraph = self.find_song_info_paragraph(content_div)

            if song_info_paragraph:
                # Parse other metadata fields
                artist = self.extract_field(song_info_paragraph, 'Artist:')
                bpm = self.extract_ddr_value(self.extract_field(song_info_paragraph, 'BPM:'))
                length = self.extract_ddr_value(self.extract_field(song_info_paragraph, 'Length:'))
                table_data = self.extract_table(content_div)

                metadata = {
                    "Song": song,
                    "Artist": artist,
                    "BPM": bpm,
                    "Length": length,
                    "Table": table_data
                }
                self.save_metadata(list_item_text, metadata)

                # Process images within the content div
                self.process_images(content_div, list_item_text)

        except requests.exceptions.RequestException as e:
            logging.error(f'Error processing {link}: {e}')

    def extract_song(self, content_div):
        """
        Extract the song title from the <span class="mw-headline"> element within the first <h1>.

        :param content_div: The BeautifulSoup object representing the content div.
        :return: The song title, or None if not found.
        """
        h1 = content_div.find('h1')
        if h1:
            headline_span = h1.find('span', class_='mw-headline')
            if headline_span:
                return headline_span.get_text(strip=True)
        return None

    def find_song_info_paragraph(self, content_div):
        """
        Find the paragraph containing artist, BPM, and length information.

        :param content_div: The BeautifulSoup object representing the content div.
        :return: The paragraph element containing the song information, or None if not found.
        """
        paragraphs = content_div.find_all('p')
        for paragraph in paragraphs:
            if any(field in paragraph.decode_contents() for field in ['Artist:', 'BPM:', 'Length:']):
                return paragraph
        return None

    def extract_field(self, paragraph, field_name):
        """
        Extract a specific field from a paragraph.

        :param paragraph: The BeautifulSoup object representing the paragraph.
        :param field_name: The name of the field to extract (e.g., 'Artist:', 'BPM:').
        :return: The extracted field value, or None if not found.
        """
        text = paragraph.decode_contents()  # Get the raw HTML inside the paragraph
        start_index = text.find(field_name)
        if start_index != -1:
            # Extract text after the field name
            text_after_field = text[start_index + len(field_name):]

            # Stop at the first <br/> or end of the string
            end_index = text_after_field.find('<br/>')
            if end_index != -1:
                return text_after_field[:end_index].strip()
            else:
                return text_after_field.strip()
        return None

    def process_images(self, content_div, list_item_text):
        """
        Extract and download images from the content div.

        :param content_div: The BeautifulSoup object representing the content div.
        :param list_item_text: The text of the list item (used for naming the directory).
        """
        thumbinner_divs = content_div.find_all('div', class_='thumbinner')
        for thumb_div in thumbinner_divs:
            image_link = thumb_div.find('a', class_='image')
            if image_link:
                img_tag = image_link.find('img')
                if img_tag and 'src' in img_tag.attrs:
                    img_src = img_tag['src']

                    # Modify the src to get the full image path
                    full_image_url = self.get_full_image_url(img_src)
                    # Download the image
                    self.download_image(full_image_url, list_item_text)

    def get_full_image_url(self, img_src):
        """
        Convert the thumbnail image src to the full image URL.

        :param img_src: The source URL of the thumbnail image.
        :return: The full URL of the image.
        """
        # Remove '/thumb' from the path
        img_src = img_src.replace('/thumb', '')
        # Remove the '200px-*' part
        img_src = '/'.join(img_src.split('/')[:-1])
        # Return the full URL
        return urljoin(self.url, img_src)

    def download_image(self, img_url, list_item_text):
        """
        Download an image to the specified directory.

        :param img_url: The URL of the image to download.
        :param list_item_text: The text of the list item (used for naming the directory).
        """

        def stop_putting_stupid_shit_in_file_names(f):
            rep = {'"': '', '!': '', '?': ''}
            for old, new in rep.items():
                f = f.replace(old, new)
            return f

        try:
            img_response = requests.get(img_url, stream=True)
            img_response.raise_for_status()

            # Decode the filename from the URL
            img_filename = stop_putting_stupid_shit_in_file_names(unquote(img_url.split('/')[-1]))

            logging.info(f'Downloading image: {img_filename} from {img_url}')

            # Create a directory for the list item
            item_dir = self.output_dir / sanitize_filename(list_item_text)
            if not item_dir.exists():
                item_dir.mkdir(parents=True, exist_ok=True)
            # Save the image to the directory
            img_path = item_dir / img_filename
            with img_path.open('wb') as img_file:
                for chunk in img_response.iter_content(1024):
                    img_file.write(chunk)
            logging.info(f'Downloaded: {img_filename} to {img_path}')
        except requests.exceptions.RequestException as e:
            logging.error(f'Error downloading {img_url}: {e}')

    def extract_table(self, content_div):
        """
        Extract the specific table data from the content div.

        :param content_div: The BeautifulSoup object representing the content div.
        :return: A list of lists representing the table data, or None if not found.
        """
        tables = content_div.find_all('table', class_='wikitable')
        for table in tables:
            # Look for the table containing "Notecounts / Freeze Arrows / Shock Arrows"
            if table.find(text="Notecounts / Freeze Arrows / Shock Arrows"):
                return self.parse_table(table)
        return None  # Return None if no matching table is found

    def parse_table(self, table):
        """
        Parse a table to extract relevant data.

        :param table: The BeautifulSoup object representing the table.
        :return: A list of lists representing the table data.
        """
        table_data = []
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all(['th', 'td'])
            row_data = [cell.get_text(strip=True) for cell in cells]
            table_data.append(row_data)
        return table_data

    def save_metadata(self, list_item_text, metadata):
        """
        Save the metadata to a JSON file.

        :param list_item_text: The text of the list item (used for naming the directory).
        :param metadata: A dictionary containing the metadata to save.
        """
        item_dir = self.output_dir / sanitize_filename(list_item_text)
        if not item_dir.exists():
            item_dir.mkdir(parents=True, exist_ok=True)

        metadata_path = item_dir / 'metadata.json'
        try:
            with metadata_path.open('w') as f:
                json.dump(metadata, f, indent=4)
            logging.info(f'Saved metadata to {metadata_path}')
        except (OSError, json.JSONDecodeError) as e:
            logging.error(f'Error saving metadata for {list_item_text}: {e}')

    def process_links_in_parallel(self, links):
        """
        Process multiple links in parallel with rate limiting.

        :param links: A list of tuples containing the full URL and relative URL for each song.
        """
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for link_data in links:
                executor.submit(self.process_song, link_data)

    @staticmethod
    def extract_ddr_value(field_value, game="DanceDanceRevolution"):
        """
        Extract the value associated with DanceDanceRevolution from a string containing multiple game variants
        or return the value if no games are specified.

        :param field_value: The full string containing game-specific variants.
        :param game: The game to search for. Default is "DanceDanceRevolution".
        :return: The value associated with the specified game, or the entire value if no games are specified.
        """
        # Regular expression pattern to match the game and its associated value in parentheses
        pattern = rf'([\d:]+[-\d+:]*)\s*\(\s*[^)]*{game}[^)]*\)'

        # Search for the pattern in the field value
        match = re.search(pattern, field_value, re.IGNORECASE)

        if match:
            return match.group(1)

        # If no match, assume the value is the same across all games (no parentheses)
        return field_value.strip()
