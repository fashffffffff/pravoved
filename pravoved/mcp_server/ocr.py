from pathlib import Path

import pypdfium2 as pdfium
import pytesseract
from PIL import Image, ImageOps

# Позже движок заменим на PaddleOCR-VL-1.6, интерфейс read_scan останется прежним.

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
LANGS = "rus+eng"
TARGET_SIDE = 2000
MIN_CONFIDENCE = 60


def prepare(img):
    img = ImageOps.exif_transpose(img)
    img = ImageOps.autocontrast(img.convert("L"))
    side = max(img.size)
    if side < TARGET_SIDE:
        k = TARGET_SIDE / side
        img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    return img


def ocr_image(img):
    img = prepare(img)
    text = pytesseract.image_to_string(img, lang=LANGS)
    data = pytesseract.image_to_data(img, lang=LANGS, output_type=pytesseract.Output.DICT)
    # conf = -1 у блоков без текста
    confs = [float(c) for c, w in zip(data["conf"], data["text"]) if float(c) >= 0 and w.strip()]
    return text.strip(), confs


def read_pdf(path):
    pdf = pdfium.PdfDocument(path)
    pages = len(pdf)
    layer = [pdf[i].get_textpage().get_text_range().strip() for i in range(pages)]
    if all(layer):
        return "\n\n".join(layer), pages, None

    texts, confs = [], []
    for i in range(pages):
        img = pdf[i].render(scale=2.5).to_pil()
        t, c = ocr_image(img)
        texts.append(t)
        confs += c
    return "\n\n".join(texts), pages, confs


def read_scan(path) -> dict:
    p = Path(path)
    if not p.is_file():
        return {"error": f"файл не найден: {path}"}
    ext = p.suffix.lower()
    try:
        if ext == ".pdf":
            text, pages, confs = read_pdf(str(p))
            if confs is None:
                # текстовый слой PDF, распознавание не нужно
                return {"text": text, "pages": pages, "engine": "pdf-text", "confidence": 100.0}
        elif ext in IMAGE_EXT:
            with Image.open(p) as img:
                text, confs = ocr_image(img)
            pages = 1
        else:
            return {"error": f"формат {ext or '?'} не поддерживается, нужен jpg, png или pdf"}
    except pytesseract.TesseractNotFoundError:
        return {"error": "tesseract не установлен"}
    except Exception as e:
        return {"error": f"не удалось прочитать файл: {e}"}

    confidence = round(sum(confs) / len(confs), 1) if confs else 0.0
    res = {"text": text, "pages": pages, "engine": "tesseract", "confidence": confidence}
    if confidence < MIN_CONFIDENCE:
        res["warning"] = "текст распознан плохо, проверьте вручную"
    return res
