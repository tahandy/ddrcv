

def get_ocr_singleton():
    if not hasattr(get_ocr_singleton, 'parser'):
        from easyocr import easyocr
        # this needs to run only once to load the model into memory
        get_ocr_singleton.parser = easyocr.Reader(['en'])
    return get_ocr_singleton.parser
