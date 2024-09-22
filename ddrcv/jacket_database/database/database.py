import json
import pickle
import time
from copy import copy
from pathlib import Path
from typing import Union

import numpy as np
from PIL import Image
from encoder import Encoder
from tqdm import tqdm
import faiss


class Song:
    def __init__(self):
        self.jacket_file = None
        self.song_data = None
        self.feature_vector = None
        self.jacket_bytes = None

    def initialize(self, jacket_file, metadata_file):
        self.jacket_file = jacket_file
        self.song_data = Song.parse_metadata_file(metadata_file)
        return self

    def load_jacket_image(self, resize=None):
        img = Image.open(self.jacket_file)
        img = img.convert('RGB')
        if resize is not None:
            img = img.resize(resize)
        return img

    @staticmethod
    def parse_metadata_file(metadata_file):
        def parse_table_entry(entry):
            entry = copy(entry)
            entry = entry.replace('-', '0')
            entry = entry.split('/')
            if len(entry) == 2:
                entry.append('0')
            return [int(x) for x in entry]

        with open(metadata_file, 'r') as fid:
            orig = json.load(fid)

        # Pull over non-table data that doesn't need to be modified
        data = {k: orig[k] for k in ['Song', 'Artist', 'BPM', 'Length']}

        # Parse the table data to be in a useful format. We'll structure it as
        # Single/
        #   Beginner, Basic, Difficult, Expert, Challenge
        # Double/
        #   Basic, Difficult, Expert, Challenge
        # where each of these outputs consists of a tuple of (note count, freeze arrows, shock arrows)
        data['Single'] = dict()
        data['Single']['Beginner']  = parse_table_entry(orig['Table'][2][1])
        data['Single']['Basic']     = parse_table_entry(orig['Table'][2][2])
        data['Single']['Difficult'] = parse_table_entry(orig['Table'][2][3])
        data['Single']['Expert']    = parse_table_entry(orig['Table'][2][4])
        data['Single']['Challenge'] = parse_table_entry(orig['Table'][2][5])
        data['Double'] = dict()
        data['Double']['Basic']     = parse_table_entry(orig['Table'][2][6])
        data['Double']['Difficult'] = parse_table_entry(orig['Table'][2][7])
        data['Double']['Expert']    = parse_table_entry(orig['Table'][2][8])
        data['Double']['Challenge'] = parse_table_entry(orig['Table'][2][9])

        return data


class Database:
    DEFAULT_ENCODER_MODEL='efficientnet_b0'
    DEFAULT_ENCODER_CACHE='cache'

    def __init__(self, encoder_model=DEFAULT_ENCODER_MODEL, encoder_cache=DEFAULT_ENCODER_CACHE):
        self.encoder = Encoder(model_name=encoder_model, cache_dir=encoder_cache)
        self.songs = list()
        self.features = None


    @classmethod
    def build(cls, scrape_dir, encoder_model=DEFAULT_ENCODER_MODEL, encoder_cache=DEFAULT_ENCODER_CACHE):
        self = cls(encoder_model=encoder_model, encoder_cache=encoder_cache)
        self._build_index(scrape_dir)
        self._populate_feature_vectors()
        self._collate_feature_vectors()
        return self


    @classmethod
    def load(cls, prebuilt_pkl, encoder_cache=None):
        with open(prebuilt_pkl, 'rb') as fid:
            prebuilt = pickle.load(fid)

        metadata = prebuilt['metadata']
        if encoder_cache is not None:
            metadata['encoder_cache'] = encoder_cache
        self = cls(encoder_model=metadata['encoder_model'], encoder_cache=metadata['encoder_cache'])

        # Verify that the checksum of the loaded encoder weights matches that of the ones that built the database
        # TODO: Store encoded jpeg with the song data, enabling the ability to rebuild the database with a new
        #       encoder at runtime
        if self.encoder.checksum != metadata['encoder_checksum']:
            raise ValueError("Checksum doesn't match")

        self.songs = prebuilt['songs']
        self._collate_feature_vectors()
        return self

    def save(self, output_file):
        print(f'Saving database to {output_file}')
        metadata = {
            'encoder_model': self.encoder.model_name,
            'encoder_cache': self.encoder.cache_dir,
            'encoder_checksum': self.encoder.checksum
        }

        output = {
            'metadata': metadata,
            'songs': self.songs
        }

        with open(output_file, 'wb') as fid:
            pickle.dump(output, fid)

    def _build_index(self, scrape_dir):
        scrape_dir = Path(scrape_dir)
        jacket_files = list(scrape_dir.glob('**/*.png'))
        print(f'Building index of {len(jacket_files)} jackets')

        for jf in tqdm(jacket_files):
            jf = jf.absolute()
            self.songs.append(Song().initialize(jf, jf.parent / 'metadata.json'))

    def _populate_feature_vectors(self):
        print(f'Constructing feature vectors. This may take a minute.')
        for song in tqdm(self.songs):
            song.feature_vector = self.encoder.encode_file(song.jacket_file).tolist()

    def _collate_feature_vectors(self):
        self.features = np.array([x.feature_vector for x in self.songs], dtype=np.float32)

    def __getitem__(self, item):
        return self.songs[item]

    def __len__(self):
        return len(self.songs)

    def __iter__(self):
        return iter(self.songs)


class DatabaseLookup:
    def __init__(self, database: Database):
        self.db = database
        self.encoder = database.encoder
        self.index = self._create_faiss_index()

    @classmethod
    def from_prebuilt(cls, prebuilt_pkl, encoder_cache=None):
        return cls(Database.load(prebuilt_pkl, encoder_cache=encoder_cache))

    @staticmethod
    def normalize(array):
        return array / np.linalg.norm(array, axis=-1, keepdims=True)

    def _create_faiss_index(self):
        print('Creating FAISS index')
        tic = time.time()
        feature_matrix = np.array(np.row_stack([x.feature_vector for x in self.db])).astype(np.float32)
        feature_matrix = DatabaseLookup.normalize(feature_matrix)
        feature_len = feature_matrix.shape[1]

        index = faiss.IndexFlatIP(feature_len)
        index.add(feature_matrix)
        print(f'FAISS indexing took {time.time() - tic} seconds')
        return index

    def lookup(self, rgb_image, count=1):
        """
        HxWx3 input image
        """
        q = self.encoder.encode_numpy(rgb_image, normalize=True)
        q = q.reshape(1, -1)
        distances, indices = self.index.search(q, count)
        nearest_songs = [self.db[ii] for ii in indices]
        return distances, nearest_songs



if __name__ == "__main__":
    # db = Database.build('../output', encoder_model='efficientnet_b1', encoder_cache='cache')
    # db.save('../output/db_effnetb1.pkl')
    # db = Database.load('../output/db_effnetb1.pkl')
    db = DatabaseLookup.from_prebuilt('../output/db_effnetb1.pkl')
    a = 1

    

