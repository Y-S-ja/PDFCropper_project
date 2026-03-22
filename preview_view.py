from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QProgressBar,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QFrame,
)
from PySide6.QtCore import Qt, QEvent, QThread
from PySide6.QtGui import QPixmap, QColor, QBrush, QPen, QTransform, QPainter
import fitz
from worker import PreviewWorker, JoinPreviewWorker


class PdfPreviewView(QWidget):
    """
    切り抜き後の画像を一列に並べて表示するフルスクリーン・プレビュー
    QGraphicsView を使用することで、大量の画像があっても高速に動作する
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom_factor = 1.0

        # レイアウト
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # プログレスバー（細い青色のバー）
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #e0e0e0;
                text-align: center;
                color: #333;
                font-size: 11px;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #2196F3;
            }
        """)
        self.progress_bar.hide()
        self.main_layout.addWidget(self.progress_bar)

        # メインビュー（QGraphicsView）
        self.view = QGraphicsView()
        self.scene = QGraphicsScene(self)
        self.view.setScene(self.scene)

        # 表示の設定
        self.view.setAlignment(Qt.AlignTop | Qt.AlignCenter)
        self.view.setRenderHint(QPainter.SmoothPixmapTransform)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setFrameShape(QFrame.NoFrame)
        self.view.setBackgroundBrush(QBrush(QColor("#f0f0f0")))

        self.main_layout.addWidget(self.view)

        # バックグラウンド処理用
        self.worker = None
        self.thread = None
        self.page_slots = {}  # (page_idx, rect_idx) -> (RectItem, TextItem, y_pos, w, h)
        self.current_y = 20  # 逐次描画（連結用）で使用するY座標
        self.spacing = 30  # 画像間の余白

        # ズーム用イベントフィルタ（QGraphicsViewのViewportに設置）
        self.view.viewport().installEventFilter(self)

    def eventFilter(self, source, event):
        """Ctrl+スクロールでズーム"""
        if source == self.view.viewport() and event.type() == QEvent.Wheel:
            if event.modifiers() == Qt.ControlModifier:
                self.wheelEvent(event)
                return True
        return super().eventFilter(source, event)

    def wheelEvent(self, event):
        """Ctrl + スクロールでズーム"""
        if event.modifiers() == Qt.ControlModifier:
            angle = event.angleDelta().y()
            factor = 1.1 if angle > 0 else 0.9

            new_zoom = self.zoom_factor * factor
            # 0.1倍〜5.0倍に制限
            if 0.1 <= new_zoom <= 5.0:
                self.zoom_factor = new_zoom
                self.apply_zoom()
            event.accept()
        else:
            super().wheelEvent(event)

    def apply_zoom(self):
        """現在のズーム倍率をビューの変換として適用"""
        transform = QTransform()
        transform.scale(self.zoom_factor, self.zoom_factor)
        self.view.setTransform(transform)

    def stop_rendering(self):
        """生成処理を安全に停止する"""
        if self.worker:
            self.worker.cancel()

        try:
            # 処理が正常終了して C++ 側のスレッドオブジェクトが既に破棄されている場合、
            # isRunning() の呼び出しで RuntimeError が発生するため保護する
            if self.thread and self.thread.isRunning():
                self.thread.quit()
                self.thread.wait()
        except RuntimeError as e:
            print(f"Thread is already stopped: {e}")
            pass

        self.worker = None
        self.thread = None

    def update_previews(self, pdf_path, rects, scale_factor):
        """
        指定されたPDFと枠データに基づいてプレビューの生成を開始する
        """
        self.stop_rendering()

        # シーンをクリア
        self.scene.clear()
        self.page_slots.clear()

        # ズームをリセット
        self.view.setTransform(QTransform())
        self.zoom_factor = 1.0

        if not pdf_path or not rects:
            msg = self.scene.addSimpleText("表示するプレビューがありません")
            msg.setBrush(QBrush(QColor("gray")))
            self.progress_bar.hide()
            return

        # 1. ページ数の取得
        try:
            with fitz.open(pdf_path) as doc:
                page_count = len(doc)
        except Exception:
            return

        # プログレスバーの設定
        self.progress_bar.setRange(0, page_count)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"0 / {page_count} ページを処理中... (0%)")
        self.progress_bar.show()

        # 2. レイアウト計算とプレースホルダーの一括配置
        crop_coordinates = []
        current_y = 20
        spacing = 30

        box_info = []
        for box in rects:
            r = box.scene_rect
            coords = (r.left(), r.top(), r.right(), r.bottom())
            crop_coordinates.append(coords)

            f_rect = fitz.Rect(
                coords[0] * scale_factor,
                coords[1] * scale_factor,
                coords[2] * scale_factor,
                coords[3] * scale_factor,
            )
            box_info.append((f_rect.width * 2, f_rect.height * 2))

        for page_idx in range(page_count):
            for rect_idx, (w, h) in enumerate(box_info):
                rect_item = QGraphicsRectItem(0, 0, w, h)
                rect_item.setPos(0, current_y)
                rect_item.setBrush(QBrush(QColor("#e8e8e8")))
                rect_item.setPen(QPen(QColor("#cccccc"), 1))
                self.scene.addItem(rect_item)

                text_item = QGraphicsSimpleTextItem(f"Page {page_idx + 1}")
                text_item.setBrush(QBrush(QColor("#999999")))
                text_w = text_item.boundingRect().width()
                text_h = text_item.boundingRect().height()
                text_item.setPos((w - text_w) / 2, current_y + (h - text_h) / 2)
                self.scene.addItem(text_item)

                self.page_slots[(page_idx, rect_idx)] = (
                    rect_item,
                    text_item,
                    current_y,
                    w,
                    h,
                )
                current_y += h + spacing

        self.scene.setSceneRect(
            self.scene.itemsBoundingRect().adjusted(-50, -50, 50, 50)
        )

        # 別スレッドでの実行準備
        self.thread = QThread()
        self.worker = PreviewWorker(pdf_path, crop_coordinates, scale_factor, 1.0)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.page_ready.connect(self._add_page_images)
        self.worker.progress_updated.connect(self._update_progress)
        self.worker.finished.connect(self._on_finished)

        # 終了処理の接続（スレッドを止めるだけにする）
        self.worker.finished.connect(self.thread.quit)

        self.thread.start()

    def _update_progress(self, current, total):
        """プログレスバーの更新"""
        self.progress_bar.setValue(current)
        percent = int((current / total) * 100)
        self.progress_bar.setFormat(
            f"{current} / {total} ページを処理中... ({percent}%)"
        )

    def _on_finished(self):
        """処理完了時の処理"""
        self.progress_bar.hide()

    def _add_page_images(self, batch_data):
        """Workerから届いたバッチ（複数ページ分）の画像をシーン上のプレースホルダーの位置に配置する"""
        if not batch_data:
            return

        for page_idx, images in batch_data:
            for i, q_img in enumerate(images):
                if q_img is None:
                    continue

                if (page_idx, i) not in self.page_slots:
                    continue

                rect_item, text_item, y_pos, w, h = self.page_slots[(page_idx, i)]

                pixmap = QPixmap.fromImage(q_img)
                pix_item = QGraphicsPixmapItem(pixmap)
                pix_item.setPos(0, y_pos)
                pix_item.setTransformationMode(Qt.SmoothTransformation)

                bg_rect = QGraphicsRectItem(0, y_pos, w, h)
                bg_rect.setBrush(QBrush(Qt.white))
                bg_rect.setPen(QPen(QColor("#cccccc"), 1))
                self.scene.addItem(bg_rect)

                self.scene.addItem(pix_item)
                rect_item.setVisible(False)
                text_item.setVisible(False)

    def update_joined_previews(self, assets_metadata):
        """
        複数アセットのメタデータリストに基づいて連結プレビューの生成を開始する
        """
        self.stop_rendering()
        self.scene.clear()
        self.page_slots.clear()
        self.current_y = 20  # 初期位置をリセット

        # ズームをリセット
        self.view.setTransform(QTransform())
        self.zoom_factor = 1.0

        if not assets_metadata:
            msg = self.scene.addSimpleText("連結するアイテムがありません")
            msg.setBrush(QBrush(QColor("gray")))
            self.progress_bar.hide()
            return

        total_assets = len(assets_metadata)
        self.progress_bar.setRange(0, total_assets)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"0 / {total_assets} ファイルを解析中...")
        self.progress_bar.show()

        # スレッドの準備
        self.thread = QThread()
        self.worker = JoinPreviewWorker(assets_metadata)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.page_ready.connect(self._append_joined_images)  # こちらは逐次追加
        self.worker.progress_updated.connect(self._update_progress_for_join)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)

        self.thread.start()

    def _update_progress_for_join(self, current, total):
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"{current} / {total} ファイルを解析中...")

    def _append_joined_images(self, batch_data):
        """JoinWorkerから届いたバッチ（ページ単位）を描画"""
        if not batch_data:
            return

        for _, images in batch_data:
            for q_img in images:
                if q_img is None:
                    continue

                pixmap = QPixmap.fromImage(q_img)
                pix_item = QGraphicsPixmapItem(pixmap)

                # 白い背景（紙）を描画
                bg_rect = QGraphicsRectItem(
                    0, self.current_y, pixmap.width(), pixmap.height()
                )
                bg_rect.setBrush(QBrush(Qt.white))
                bg_rect.setPen(QPen(QColor("#cccccc"), 1))
                self.scene.addItem(bg_rect)

                pix_item.setPos(0, self.current_y)
                pix_item.setTransformationMode(Qt.SmoothTransformation)
                self.scene.addItem(pix_item)

                self.current_y += pixmap.height() + self.spacing

        self.scene.setSceneRect(
            self.scene.itemsBoundingRect().adjusted(-50, -50, 50, 50)
        )
