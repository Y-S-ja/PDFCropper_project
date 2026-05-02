from __future__ import annotations

from io import BytesIO
from pypdf import PdfReader, PdfWriter


def normalize_pdf_rotation_to_bytes(pdf_path: str) -> bytes | None:
    """
    PDFページの回転属性(/Rotate)をコンテンツに転写して正規化する。

    Returns:
        bytes: 正規化後PDFのバイナリ
        None: 全ページの回転が0で、正規化不要だった場合
    """
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    changed = False

    for page in reader.pages:
        current_rot = int(page.get("/Rotate", 0) or 0)
        if current_rot != 0:
            page.transfer_rotation_to_content()
            changed = True
        writer.add_page(page)

    if not changed:
        return None

    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def normalize_pdf_rotation_to_file(input_path: str, output_path: str) -> bool:
    """
    回転正規化したPDFを output_path に保存する。

    Returns:
        True: 正規化して保存した
        False: 正規化不要で未保存
    """
    normalized = normalize_pdf_rotation_to_bytes(input_path)
    if normalized is None:
        return False

    with open(output_path, "wb") as f:
        f.write(normalized)
    return True