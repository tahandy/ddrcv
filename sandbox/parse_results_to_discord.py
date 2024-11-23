import os

os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

from pprint import pprint
import time
import cv2
from easyocr import easyocr

from ddrcv.discord.song_results_embed import push_song_results
from ddrcv.jacket_database.database.database import DatabaseLookup
from sandbox.parse_results_updated import ResultsParser


if __name__ == "__main__":
    reader = easyocr.Reader(['en'])

    file = '../state_images/results_updated.png'
    img = cv2.imread(file, cv2.IMREAD_UNCHANGED)

    database = DatabaseLookup.from_prebuilt('../ddrcv/jacket_database/output/db_effnetb0.pkl')
    parser = ResultsParser(reader, database)

    tic = time.time()
    results = parser.parse(img)
    pprint(results)
    print(f'Results parsing took {time.time() - tic:.3f} seconds')

    push_song_results(results, screenshot_path=file)
