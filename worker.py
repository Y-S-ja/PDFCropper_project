from PySide6.QtCore import QObject, Signal, Qt, QThread
from pdf_processor import PdfProcessor
import fitz


class PreviewWorker(QObject):
    """
    バックグラウンドでPDFのプレビュー画像を生成するクラス
    """

    page_ready = Signal(list)  # [(page_idx, QImageのリスト), ...] のリスト
    finished = Signal()
    error = Signal(str)

    def __init__(self, pdf_path, crop_coords, scale_factor, zoom_factor):
        super().__init__()
        self.pdf_path = pdf_path
        self.crop_coords = crop_coords
        self.scale_factor = scale_factor
        self.zoom_factor = zoom_factor
        self._is_cancelled = False

    def cancel(self):
        """処理を中断するフラグを立てる"""
        self._is_cancelled = True

    def run(self):
        """実際の変換処理（別スレッドで実行される）"""
        try:
            with fitz.open(self.pdf_path) as doc:
                total_pages = len(doc)
                batch = []
                batch_size = 5

                for page_idx in range(total_pages):
                    if self._is_cancelled:
                        break

                    # 1ページ分の抽出 (QImageのリストが返ってくる)
                    images = PdfProcessor._get_previews_for_page(
                        doc,
                        page_idx,
                        self.crop_coords,
                        self.scale_factor,
                        preview_dpi=144,
                    )

                    # --- 画像加工（リサイズ）をWorker側で実行 ---
                    processed_images = []
                    for img in images:
                        if img is None:
                            processed_images.append(None)
                            continue

                        # ズーム倍率に合わせてリサイズ
                        target_size = img.size() * self.zoom_factor
                        scaled_img = img.scaled(
                            target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                        )
                        processed_images.append(scaled_img)

                    # バッチに追加
                    batch.append((page_idx, processed_images))

                    # 一定量たまったら送信
                    if len(batch) >= batch_size:
                        self.page_ready.emit(batch)
                        batch = []
                        # まとめて更新した後は少し長めに休む（UIに描画チャンスを確実に与える）
                        QThread.msleep(30)
                    else:
                        # 毎回の微小スリープも継続
                        QThread.msleep(5)

                # 最後の未送信分があれば送信
                if batch and not self._is_cancelled:
                    self.page_ready.emit(batch)

            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))
