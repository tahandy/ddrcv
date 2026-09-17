from .ocr_singleton import get_ocr_singleton
from .utils import get_best_match_from_results
from .rapid import OCRResult, RapidOCRRecognizer, get_rapidocr, prepare_ddr_crop

__all__ = [
    'get_ocr_singleton', 'get_best_match_from_results',
    'OCRResult', 'RapidOCRRecognizer', 'get_rapidocr', 'prepare_ddr_crop',
]
