import fitz
from PySide6.QtGui import QImage, QPixmap
import os

class PdfProcessor:
    """PDFの操作に関するすべてのロジックをカプセル化するクラス"""

    @staticmethod
    def get_page_image(pdf_path: str, page_index: int = 0, scale: float = 3.0) -> tuple:
        """指定したPDFページを高画質で画像化して返す"""
        doc = fitz.open(pdf_path)
        page = doc[page_index]
        
        # 画像化
        matrix = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=matrix)
        
        # PyMuPDFのデータからQPixmapを生成
        img_data = pix.tobytes("png")
        image = QImage.fromData(img_data)
        pixmap = QPixmap.fromImage(image)
        
        original_width = page.rect.width
        doc.close()
        
        # 画像と、後で座標変換に使う「元の幅」を返す
        return pixmap, original_width

    @staticmethod
    def crop_and_save(input_path: str, output_path: str, crop_rects: list, scale_factor: float):
        """
        クロップ処理を行い、新しいPDFとして保存する
        crop_rects: [(left, top, right, bottom), ...] のような数値タプルのリスト
        """
        src_doc = fitz.open(input_path)
        new_doc = fitz.open()

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
        new_doc.close()
        src_doc.close()

    @staticmethod
    def get_preview_images(pdf_path: str, crop_rects: list, scale_factor: float):
        """
        クロップ枠ごとのプレビュー画像をリストで返す
        crop_rects: [(l, t, r, b), (l, t, r, b), ...]  ← 純粋な座標のリスト
        """
        doc = fitz.open(pdf_path)
        previews = []
        
        for page_index in range(len(doc)):
            page = doc[page_index]
            for i, rect in enumerate(crop_rects):
                left, top, right, bottom = rect
                fitz_rect = fitz.Rect(left * scale_factor, top * scale_factor, 
                                    right * scale_factor, bottom * scale_factor)
                
                if fitz_rect.is_empty: continue
                
                pix = page.get_pixmap(clip=fitz_rect, matrix=fitz.Matrix(2, 2))
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                
                # (ページ番号, 元のリスト内でのインデックス, 画像) を返す
                previews.append((page_index, i, QPixmap.fromImage(img)))
                
        doc.close()
        return previews