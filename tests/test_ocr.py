import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from pravoved.mcp_server.ocr import read_scan

TEXT = "ПРЕТЕНЗИЯ о возврате денежных средств, статья 18 Закона"
FONTS = ["/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"]


def find_font():
    for f in FONTS:
        if Path(f).exists():
            return f
    return None


def make_image(path):
    font = ImageFont.truetype(find_font(), 40)
    img = Image.new("RGB", (1500, 120), "white")
    ImageDraw.Draw(img).text((20, 30), TEXT, fill="black", font=font)
    img.save(path)


needs_ocr = pytest.mark.skipif(
    shutil.which("tesseract") is None or find_font() is None,
    reason="нет tesseract или кириллического шрифта",
)


@needs_ocr
def test_read_image(tmp_path):
    path = tmp_path / "scan.png"
    make_image(path)
    res = read_scan(path)
    print(res["text"], res["confidence"])
    low = res["text"].lower()
    found = [w for w in ("претензия", "денежных", "закона") if w in low]
    assert len(found) >= 2
    assert res["engine"] == "tesseract"
    assert res["pages"] == 1
    assert 0 <= res["confidence"] <= 100


@needs_ocr
def test_read_scanned_pdf(tmp_path):
    img = tmp_path / "scan.png"
    make_image(img)
    pdf = tmp_path / "scan.pdf"
    Image.open(img).save(pdf)
    res = read_scan(pdf)
    assert res["pages"] == 1
    assert "претензия" in res["text"].lower()


def test_pdf_with_text_layer(tmp_path):
    # минимальный PDF руками, латиница в стандартном шрифте
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        "<< /Length 44 >>\nstream\nBT /F1 18 Tf 20 100 Td (Claim text) Tj ET\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = "%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n"
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    path = tmp_path / "text.pdf"
    path.write_bytes(out.encode("latin-1"))

    res = read_scan(path)
    assert "Claim text" in res["text"]
    assert res["pages"] == 1


def test_missing_file(tmp_path):
    res = read_scan(tmp_path / "nope.png")
    assert "error" in res


def test_bad_format(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("привет")
    assert "error" in read_scan(f)
