from PySide6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QLabel, QFrame
from PySide6.QtCore import Qt, QCoreApplication
from pdf_processor import PdfProcessor


class PdfPreviewView(QWidget):
    """切り抜き後の画像を一列に並べて表示するフルスクリーン・プレビュー"""

    def __init__(self, parent=None):
        super().__init__(parent)
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

    def update_previews(self, pdf_path, rects, scale_factor):
        """
        指定されたPDFと枠データに基づいてプレビューを再構築する
        """
        # 既存の表示をクリア
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
            # ページ区切りラベル
            page_header = QLabel(f"--- ページ {page_idx + 1} ---")
            page_header.setStyleSheet(
                "font-weight: bold; color: white; background-color: #555; padding: 10px; border-radius: 5px;"
            )
            page_header.setAlignment(Qt.AlignCenter)
            page_header.setFixedWidth(400)
            # self.container_layout.addWidget(page_header, 0, Qt.AlignCenter)

            for i, pixmap in enumerate(images):
                if pixmap is None:
                    continue

                # 枠番号ラベル
                rect_num = rects[i].rect_id
                info_label = QLabel(f"枠 {rect_num}")
                info_label.setStyleSheet("font-weight: bold; font-size: 14px;")

                # 画像表示ラベル
                img_label = QLabel()
                img_label.setPixmap(pixmap)
                img_label.setFrameShape(QFrame.StyledPanel)
                img_label.setStyleSheet(
                    "border: 1px solid #ccc; background-color: white;"
                )

                # アイテム用コンテナ
                item_widget = QWidget()
                item_layout = QVBoxLayout(item_widget)
                # item_layout.addWidget(info_label, 0, Qt.AlignCenter)
                item_layout.addWidget(img_label, 0, Qt.AlignCenter)

                self.container_layout.addWidget(item_widget)

                # 処理の合間にイベントループを回してフリーズを防ぐ
                QCoreApplication.processEvents()
