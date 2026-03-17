from PySide6.QtCore import QObject, Signal
from pdf_processor import PdfProcessor
import fitz


class PreviewWorker(QObject):
    """
    バックグラウンドでPDFのプレビュー画像を生成するクラス
    """

    page_ready = Signal(int, list)  # ページ番号, QPixmapのリスト
    finished = Signal()
    error = Signal(str)

    def __init__(self, pdf_path, crop_coords, scale_factor):
        super().__init__()
        self.pdf_path = pdf_path
        self.crop_coords = crop_coords
        self.scale_factor = scale_factor
        self._is_cancelled = False

    def cancel(self):
        """処理を中断するフラグを立てる"""
        self._is_cancelled = True

    def run(self):
        """実際の変換処理（別スレッドで実行される）"""
        try:
            # 内部関数 _get_previews_for_page を活用して生成
            with fitz.open(self.pdf_path) as doc:
                total_pages = len(doc)
                for page_idx in range(total_pages):
                    if self._is_cancelled:
                        break

                    # 1ページ分の抽出
                    pixmaps = PdfProcessor._get_previews_for_page(
                        doc,
                        page_idx,
                        self.crop_coords,
                        self.scale_factor,
                        preview_dpi=144,
                    )

                    # メインスレッドに結果を送信
                    self.page_ready.emit(page_idx, pixmaps)

            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))
