from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QLabel, QFrame
from PySide6.QtCore import Qt, QCoreApplication
from pdf_processor import PdfProcessor


class PdfPreviewView(QWidget):
    """切り抜き後の画像を一列に並べて表示するフルスクリーン・プレビュー"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom_factor = 1.0
        self.preview_items = []  # (QLabel, QPixmap) のリスト
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

    def update_previews(self, pdf_path, rects, scale_factor):
        """
        指定されたPDFと枠データに基づいてプレビューを再構築する
        """
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

        # ジェネレータを開始
        generator = PdfProcessor.generate_all_previews(
            pdf_path, crop_coordinates, scale_factor
        )

        for page_idx, images in generator:
            for i, pixmap in enumerate(images):
                if pixmap is None:
                    continue

                # 画像表示ラベル
                img_label = QLabel()
                # 初期表示も現在のズームを適用
                scaled_size = pixmap.size() * self.zoom_factor
                img_label.setPixmap(
                    pixmap.scaled(
                        scaled_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                )
                img_label.setFrameShape(QFrame.StyledPanel)
                img_label.setStyleSheet(
                    "border: 1px solid #ccc; background-color: white;"
                )

                # アイテム用コンテナ
                item_widget = QWidget()
                item_layout = QVBoxLayout(item_widget)
                item_layout.addWidget(img_label, 0, Qt.AlignCenter)

                self.container_layout.addWidget(item_widget)
                self.preview_items.append((img_label, pixmap))

                # 処理の合間にイベントループを回してフリーズを防ぐ
                QCoreApplication.processEvents()
