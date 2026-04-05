from PySide6.QtCore import QObject, Signal, Qt, QThread
from PySide6.QtGui import QImage
from pdf_processor import PdfProcessor
import fitz


class PreviewWorker(QObject):
    """
    バックグラウンドでPDFのプレビュー画像を生成するクラス
    """

    page_ready = Signal(list)  # [(page_idx, QImageのリスト), ...] のリスト
    progress_updated = Signal(int, int)  # current, total
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
                if total_pages == 0:
                    return

                batch = []
                batch_size = 5

                for page_idx in range(total_pages):
                    if self._is_cancelled:
                        return

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

                    # 進捗を通知
                    self.progress_updated.emit(page_idx + 1, total_pages)

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

        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class JoinPreviewWorker(QObject):
    """
    連結リストのアセット群からプレビュー画像を順次生成する
    """

    page_ready = Signal(list)  # [(index, QImageのリスト), ...]
    progress_updated = Signal(int, int)  # current, total
    finished = Signal()
    error = Signal(str)

    def __init__(self, assets_metadata, preview_dpi=144):
        super().__init__()
        self.assets_metadata = assets_metadata
        self.preview_dpi = preview_dpi
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        """リスト上の全アセットを順に処理し、画像を生成する"""
        try:
            total_items = len(self.assets_metadata)
            if total_items == 0:
                return

            batch = []
            batch_size = 5
            global_idx = 0

            for i, meta in enumerate(self.assets_metadata):
                if self._is_cancelled:
                    return

                path = meta["path"]
                crop_coords = meta["crop_coords"]
                scale_factor = meta["scale_factor"]

                try:
                    with fitz.open(path) as doc:
                        for page_idx in range(len(doc)):
                            if self._is_cancelled:
                                return

                            if not crop_coords:
                                # 全ページ表示の場合
                                pix = doc[page_idx].get_pixmap(dpi=self.preview_dpi)
                                img = QImage(
                                    pix.samples,
                                    pix.width,
                                    pix.height,
                                    pix.stride,
                                    QImage.Format_RGB888,
                                ).copy()
                                batch.append((global_idx, [img]))
                                global_idx += 1
                            else:
                                # 切り抜き表示の場合
                                page_previews = PdfProcessor._get_previews_for_page(
                                    doc,
                                    page_idx,
                                    crop_coords,
                                    scale_factor,
                                    self.preview_dpi,
                                )
                                # 有効な画像だけを抽出
                                valid_imgs = [img for img in page_previews if img]
                                if valid_imgs:
                                    batch.append((global_idx, valid_imgs))
                                    global_idx += 1

                            # 進捗通知（アセット単位 + 詳細の微調整などは呼び出し側で想定）
                            self.progress_updated.emit(i + 1, total_items)

                            # バッチ送信
                            if len(batch) >= batch_size:
                                self.page_ready.emit(batch)
                                batch = []
                                QThread.msleep(30)
                            else:
                                QThread.msleep(5)

                except Exception as e:
                    print(f"Error processing {path} in JoinWorker: {e}")

            # 残りのバッチを送信
            if batch and not self._is_cancelled:
                self.page_ready.emit(batch)

        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class OrganizePreviewWorker(QObject):
    """
    OrganizeDesk用の、ハイブリッド（PDFページ + 画像ファイル）プレビュー生成ワーカー
    """

    page_ready = Signal(list)  # [(metadata, generated_image), ...] のリスト
    progress_updated = Signal(int, int)  # (current, total)
    finished = Signal()
    error = Signal(str)

    def __init__(self, request_list):
        """
        request_list: [{"type": "...", "source_path": "...", "page_index": N}, ...]
        """
        super().__init__()
        self.request_list = request_list
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            # 同じPDFを何度も開きなおさないためのキャッシュ
            pdf_docs = {}
            import os

            total_items = len(self.request_list)
            batch = []
            batch_size = 5

            for i, metadata in enumerate(self.request_list):
                if self._is_cancelled:
                    break

                img = None
                m_type = metadata.get("type")
                m_path = metadata.get("source_path")
                m_page = metadata.get("page_index")

                if not m_path or not os.path.exists(m_path):
                    continue

                try:
                    if m_type == "pdf_page":
                        # PDFから1ページ分をレンダリング
                        if m_path not in pdf_docs:
                            pdf_docs[m_path] = fitz.open(m_path)

                        doc = pdf_docs[m_path]
                        if 0 <= m_page < len(doc):
                            page = doc[m_page]
                            # 144dpi相当 (72 * 2.0)
                            mat = fitz.Matrix(2.0, 2.0)
                            pix = page.get_pixmap(matrix=mat)
                            img = QImage(
                                pix.samples,
                                pix.width,
                                pix.height,
                                pix.stride,
                                QImage.Format_RGB888,
                            )

                    elif m_type == "image_file":
                        # 画像ファイルを直接読み込み
                        img = QImage(m_path)
                        if not img.isNull():
                            # 適度なサイズに縮小（アスペクト比維持）
                            img = img.scaled(
                                200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation
                            )

                    if img and not img.isNull():
                        # item_id と画像のペアをバッチに保存
                        item_id = metadata.get("item_id")
                        batch.append((item_id, img.copy()))

                    # 進捗通知
                    self.progress_updated.emit(i + 1, total_items)

                    # バッチ送信判定
                    if len(batch) >= batch_size:
                        self.page_ready.emit(batch)
                        batch = []
                        # 溜まったデータを一気にUIへ送った直後は、UIスレッドが描画する時間を稼ぐために少し長めに休む
                        QThread.msleep(30)
                    else:
                        # 毎回の微小な休止
                        QThread.msleep(5)

                except Exception as e:
                    print(f"Error rendering item in OrganizeWorker: {e}")

            # 残りのバッチがあれば送信
            if batch and not self._is_cancelled:
                self.page_ready.emit(batch)

            # 開いたPDFを全て閉じる
            for doc in pdf_docs.values():
                doc.close()

        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()
