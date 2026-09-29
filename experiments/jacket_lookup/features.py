"""CPU encoders and portable indexes. Heavy research imports are lazy."""
from __future__ import annotations

import hashlib
from pathlib import Path
import time

import cv2
import numpy as np

from .catalog import dump_json, read_json, sha256
from .corpus import read_image

METHODS = ('classical', 'sift', 'mobilenet', 'efficientnet')


from ddrcv.jacket_lookup.features import unit, resize, classical

class Encoder:
    def __init__(self, method='classical', size=128, model_dir=None):
        if method not in METHODS or size not in (128, 150):
            raise ValueError('Unsupported method or reference resolution')
        self.method, self.size = method, size
        self.model_dir = Path(model_dir or Path(__file__).parent / 'models')
        self.model = None
        self.fingerprint = 'color-gradient-v1'
        cv2.setNumThreads(1)
        if method == 'mobilenet':
            import onnxruntime as ort
            path = self.model_dir / 'mobilenet_v3_small.onnx'
            meta = read_json(self.model_dir / 'mobilenet_v3_small.json')
            self.fingerprint = sha256(path.read_bytes())
            if self.fingerprint != meta['sha256']:
                raise ValueError('MobileNet model checksum mismatch')
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = opts.inter_op_num_threads = 1
            opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            self.model = ort.InferenceSession(str(path), opts, providers=['CPUExecutionProvider'])
        elif method == 'efficientnet':
            import torch
            import timm
            torch.set_num_threads(1)
            path = self.model_dir / 'efficientnet_b0.pth'
            if not path.exists():
                raise FileNotFoundError('Legacy EfficientNet baseline requires its existing local weights')
            self.fingerprint = sha256(path.read_bytes())
            self.model = timm.create_model('efficientnet_b0', pretrained=False,
                                          checkpoint_path=str(path), num_classes=1000)
            self.model.reset_classifier(0)
            self.model.cpu().eval()

    def encode(self, image):
        if image.shape[:2] != (self.size, self.size):
            image = resize(image, self.size)
        if self.method in ('classical', 'sift'):
            return classical(image)
        rgb = resize(image, 224)[..., ::-1].astype(np.float32) / 255
        tensor = ((rgb - np.array([.485, .456, .406], np.float32)) /
                  np.array([.229, .224, .225], np.float32)).transpose(2, 0, 1)[None]
        tensor = np.ascontiguousarray(tensor)
        if self.method == 'mobilenet':
            features = self.model.run(None, {self.model.get_inputs()[0].name: tensor})[0]
        else:
            import torch
            with torch.inference_mode():
                features = self.model(torch.from_numpy(tensor)).numpy()
        return unit(features)


def build_index(catalog_path, out, *, method='classical', size=128, model_dir=None):
    from ddrcv.jacket_lookup.features import build_index as build
    return build(catalog_path, out, method=method, size=size,
                 model_dir=model_dir, encoder_factory=Encoder)


def export_mobilenet(out):
    """Development-only export; never called by the user installer."""
    import torch
    import torchvision
    from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(1)
    torch.hub.set_dir(str(out / 'torch-cache'))
    model = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1)
    # Feature pooling before the classifier: 576-dimensional identity descriptor.
    feature_model = torch.nn.Sequential(model.features, model.avgpool, torch.nn.Flatten()).eval()
    path = out / 'mobilenet_v3_small.onnx'
    torch.onnx.export(feature_model, torch.zeros(1, 3, 224, 224), str(path),
                      input_names=['image'], output_names=['embedding'], opset_version=17,
                      do_constant_folding=True)
    dump_json(out / 'mobilenet_v3_small.json', dict(sha256=sha256(path.read_bytes()),
        source='torchvision MobileNet_V3_Small_Weights.IMAGENET1K_V1',
        torch=torch.__version__, torchvision=torchvision.__version__,
        preprocessing='shared-resolution square jacket; RGB resize 224; ImageNet mean/std',
        feature='features -> avgpool -> flatten; L2 normalization outside graph'))
    return path
