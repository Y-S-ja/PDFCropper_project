import fitz
from PySide6.QtGui import QImage, QPixmap
import os

class PdfProcessor:
    """PDFの操作に関するすべてのロジックをカプセル化するクラス"""

    @staticmethod
    def get_page_image(pdf_path: str, page_index: int = 0, dpi: int = 216) -> tuple:
        """指定したPDFページを高画質で画像化して返す (標準72dpiに対して216dpi = 3倍画質)"""
        with fitz.open(pdf_path) as doc:
            page = doc[page_index]
            
            # DPI指定で画像化
            pix = page.get_pixmap(dpi=dpi)
            
            # PyMuPDFのデータからQPixmapを生成
            img_data = pix.tobytes("png")
            image = QImage.fromData(img_data)
            pixmap = QPixmap.fromImage(image)
            
            original_width = page.rect.width
            
            # 画像と、後で座標変換に使う「元の幅」を返す
            return pixmap, original_width

    @staticmethod
    def crop_and_save(input_path: str, output_path: str, crop_rects: list, scale_factor: float):
        """
        クロップ処理を行い、新しいPDFとして保存する
        crop_rects: [(left, top, right, bottom), ...] のような数値タプルのリスト
        """
        with fitz.open(input_path) as src_doc:
            with fitz.open() as new_doc:
                for page_index in range(len(src_doc)):
                    for rect in crop_rects:
                        new_doc.insert_pdf(src_doc, from_page=page_index, to_page=page_index)
                        
                        # UIのオブジェクト(QRectF等)ではなく、ただの数値(タプル)として受け取る
                        left, top, right, bottom = rect
                        
                        # シーン座標をPDFのピクセル座標に変換
                        pdf_rect = fitz.Rect(
                            left * scale_factor, 
                            top * scale_factor, 
                            right * scale_factor, 
                            bottom * scale_factor
                        )
                        new_doc[-1].set_cropbox(pdf_rect)

                new_doc.save(output_path)

    @staticmethod
    def generate_all_previews(pdf_path: str, crop_coords: list, scale_factor: float, preview_dpi: int = 144):
        """
        全ページをスキャンし、1ページ分の画像リストを順番に yield するジェネレータ。
        crop_coords: [(l, t, r, b), ...] のリスト
        preview_dpi: 144dpi (標準72dpiの2倍)
        """
        # ループの最初に1回だけPDFを開く
        with fitz.open(pdf_path) as doc:
            for page_index in range(len(doc)):
                page = doc[page_index]
                page_pixmaps = []
                
                for rect in crop_coords:
                    l, t, r, b = rect
                    # fitz用の矩形を作成
                    fitz_rect = fitz.Rect(l * scale_factor, t * scale_factor, 
                                         r * scale_factor, b * scale_factor)
                    
                    if fitz_rect.is_empty:
                        page_pixmaps.append(None)
                        continue
                    
                    # 画像生成 (DPI指定)
                    pix = page.get_pixmap(clip=fitz_rect, dpi=preview_dpi)
                    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                    page_pixmaps.append(QPixmap.fromImage(img))
                
                # 1ページ分の画像リストが完成したら yield (ここで一時停止してUIへ渡す)
                yield page_index, page_pixmaps