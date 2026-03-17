from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QLabel, QFrame
from PySide6.QtCore import Qt, QEvent, QThread
from PySide6.QtGui import QPixmap
from worker import PreviewWorker


class PdfPreviewView(QWidget):
    """切り抜き後の画像を一列に並べて表示するフルスクリーン・プレビュー"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom_factor = 1.0
        self.preview_items = []  # (QLabel, QPixmap) のリスト

        # バックグラウンド処理用
        self.worker = None
        self.thread = None

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # スクロールエリア
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)

        # 中身のコンテナ
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignTop | Qt.AlignCenter)
        self.container_layout.setSpacing(30)  # 画像間のスペース

        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll)

        # スクロールを伴わないズームを実現するためにイベントフィルタを設置
        self.scroll.viewport().installEventFilter(self)

    def eventFilter(self, source, event):
        """イベントを横取りして Ctrl+スクロール の際のスクロールを止める"""
        if source == self.scroll.viewport() and event.type() == QEvent.Wheel:
            if event.modifiers() == Qt.ControlModifier:
                # 自前のホイールイベント（ズーム）を呼び出す
                self.wheelEvent(event)
                # Trueを返すと、そのイベントはここで消費され、
                # スクロールエリア自体のスクロール処理は走らない
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
        """現在のズーム倍率をすべての画像に適用"""
        for label, original_pixmap in self.preview_items:
            if original_pixmap.isNull():
                continue
            scaled_size = original_pixmap.size() * self.zoom_factor
            scaled_pix = original_pixmap.scaled(
                scaled_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            label.setPixmap(scaled_pix)

    def stop_rendering(self):
        """生成処理を安全に停止する"""
        if self.worker:
            self.worker.cancel()
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()
        self.worker = None
        self.thread = None

    def update_previews(self, pdf_path, rects, scale_factor):
        """
        指定されたPDFと枠データに基づいてプレビューの生成を開始する（非同期）
        """
        # 前回の処理があれば停止
        self.stop_rendering()

        # 既存の表示をクリア
        self.preview_items.clear()
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not pdf_path or not rects:
            msg = QLabel("表示するプレビューがありません")
            msg.setStyleSheet("color: gray; font-size: 18px;")
            self.container_layout.addWidget(msg, 0, Qt.AlignCenter)
            return

        # 座標抽出
        crop_coordinates = []
        for box in rects:
            r = box.scene_rect
            crop_coordinates.append((r.left(), r.top(), r.right(), r.bottom()))

        # 別スレッドでの実行準備
        self.thread = QThread()
        self.worker = PreviewWorker(
            pdf_path, crop_coordinates, scale_factor, self.zoom_factor
        )
        self.worker.moveToThread(self.thread)

        # 信号の接続
        self.thread.started.connect(self.worker.run)
        self.worker.page_ready.connect(self._add_page_images)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        # 処理開始
        self.thread.start()

    def _add_page_images(self, page_idx, images):
        """Workerから送られてきた1ページ分の画像をUIに追加する"""
        for i, q_img in enumerate(images):
            if q_img is None:
                continue

            # 画像表示ラベル
            img_label = QLabel()
            # Worker ですでにリサイズ済みなので Pixmap に変換するだけ
            pixmap = QPixmap.fromImage(q_img)
            img_label.setPixmap(pixmap)
            img_label.setFrameShape(QFrame.StyledPanel)
            img_label.setStyleSheet("border: 1px solid #ccc; background-color: white;")

            # アイテム用コンテナ
            item_widget = QWidget()
            item_layout = QVBoxLayout(item_widget)
            item_layout.addWidget(img_label, 0, Qt.AlignCenter)

            self.container_layout.addWidget(item_widget)
            # ズーム用に現在の pixmap を保持（再ズーム時はこれを使用）
            self.preview_items.append((img_label, pixmap))
