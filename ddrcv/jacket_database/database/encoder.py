from copy import copy

import timm
import numpy as np
from pathlib import Path
import torch
from PIL import Image
from torchvision import transforms

from ddrcv.jacket_database.database.checksum import compute_checksum, save_checksum_to_file


class Encoder:
    """ A class for holding the encoder model for image similarity search."""
    def __init__(self, model_name='efficientnet_b0', cache_dir='cache'):
        """
        Parameters:
        -----------
        model_name : str, optional (default='efficientnet_b0')
        The name of the pre-trained model to use for feature extraction.
        """
        self.model_name = model_name
        self.cache_dir = cache_dir

        self.cache_dir = Path(self.cache_dir)
        self.cache_dir.mkdir(exist_ok=True, parents=True)

        # Set the output weights path to be a known location, rather than the
        # default timm location that buries it deep inside the user directory
        weights_file = self.cache_dir / f'{self.model_name}.pth'

        weights_exist = weights_file.exists()

        if weights_exist:
            print(f'Weight file found at {weights_file}')

        # Load the pre-trained model and remove the last layer
        print("Please Wait Model Is Loading or Downloading From Server!")
        base_model = timm.create_model(self.model_name,
                                       pretrained=not weights_exist,
                                       checkpoint_path=str(weights_file) if weights_exist else '')

        if not weights_file.exists():
            torch.save(base_model.state_dict(), weights_file)
            base_model = timm.create_model(self.model_name, pretrained=False, checkpoint_path=str(weights_file))

        # Write the checksum of the weights file to ensure that built databases know if the loaded weights change
        # (and, consequently, that the database is invalid)
        self.checksum = compute_checksum(weights_file, algorithm='sha256', chunk_size=4096)
        save_checksum_to_file(self.checksum, weights_file.with_suffix('.sha256_4096'))
        print(f'Checksum: {self.checksum}')

        # Remove the classification layer, leaving us with the final FC layer (our encoding)
        self.model = torch.nn.Sequential(*list(base_model.children())[:-1])

        # Save normalization values
        self.input_shape = base_model.pretrained_cfg['input_size'][1:]
        self.preprocess = transforms.Compose([
            transforms.ToTensor(),
            transforms.Resize(self.input_shape, transforms.InterpolationMode.BILINEAR),
            transforms.Normalize(mean=base_model.pretrained_cfg['mean'], std=base_model.pretrained_cfg['std'])
        ])

        # Set the model to inference
        self.model.eval()
        print(f"Model Loaded Successfully: {model_name}")

    def encode_file(self, img_path, normalize=True):
        img = Image.open(img_path)
        img = img.convert('RGB')
        return self.encode_numpy(np.array(img), normalize=normalize)

    def encode_numpy(self, img, normalize=True):
        with torch.no_grad():
            img = self.preprocess(img).unsqueeze(0)
            features = self.model(img)
        features = features.cpu().numpy()[0]
        if normalize:
            features = features / np.linalg.norm(features)
        return features



if __name__ == "__main__":
    encoder = Encoder()
    print(encoder.encode_file('../output/3y3s/3y3s_DDR.png'))
    print(encoder.encode_file('../output/3y3s/3y3s.png'))
