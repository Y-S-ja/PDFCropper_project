from PySide6.QtWidgets import (
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
from worker import PreviewWorker


class PdfPreviewView(QGraphicsView):
    """
    切り抜き後の画像を一列に並べて表示するフルスクリーン・プレビュー
    QGraphicsView を使用することで、大量の画像があっても高速に動作する
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom_factor = 1.0
        self.preview_items = []  # Added PixmapItems

        # シーンの設定
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        # 表示の設定
        self.setAlignment(Qt.AlignTop | Qt.AlignCenter)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setFrameShape(QFrame.NoFrame)
        self.setBackgroundBrush(QBrush(QColor("#f0f0f0")))

        # バックグラウンド処理用
        self.worker = None
        self.thread = None
        self.page_slots = {}  # (page_idx, rect_idx) -> (RectItem, TextItem, PlaceholderGroup)

        # ズーム用イベントフィルタ（QGraphicsView本体に設置）
        self.viewport().installEventFilter(self)

    def eventFilter(self, source, event):
        """Ctrl+スクロールでズーム"""
        if source == self.viewport() and event.type() == QEvent.Wheel:
            if event.modifiers() == Qt.ControlModifier:
                # 自前のホイールイベント（ズーム）を呼び出す
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
        # QGraphicsView の機能で一括ズーム
        transform = QTransform()
        transform.scale(self.zoom_factor, self.zoom_factor)
        self.setTransform(transform)

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
        指定されたPDFと枠データに基づいてプレビューの生成を開始する
        """
        self.stop_rendering()

        # シーンをクリア
        self.scene.clear()
        self.page_slots.clear()
        self.preview_items.clear()

        # ズーム倍率を等倍に戻してからレイアウト計算（座標の一貫性のため）
        # ただし、描画は transform で行われる
        self.setTransform(QTransform())
        self.zoom_factor = 1.0

        if not pdf_path or not rects:
            msg = self.scene.addSimpleText("表示するプレビューがありません")
            msg.setBrush(QBrush(QColor("gray")))
            return

        # 1. ページ数の取得
        try:
            with fitz.open(pdf_path) as doc:
                page_count = len(doc)
        except Exception:
            return

        # 2. レイアウト計算とプレースホルダーの一括配置
        crop_coordinates = []
        current_y = 20
        spacing = 30

        # 各枠のサイズ情報
        box_info = []
        for box in rects:
            r = box.scene_rect
            coords = (r.left(), r.top(), r.right(), r.bottom())
            crop_coordinates.append(coords)

            # 144dpi基準のサイズ計算
            f_rect = fitz.Rect(
                coords[0] * scale_factor,
                coords[1] * scale_factor,
                coords[2] * scale_factor,
                coords[3] * scale_factor,
            )
            box_info.append((f_rect.width * 2, f_rect.height * 2))

        # プレースホルダーをシーンに追加
        for page_idx in range(page_count):
            for rect_idx, (w, h) in enumerate(box_info):
                # グレーの矩形（プレースホルダー）
                rect_item = QGraphicsRectItem(0, 0, w, h)
                rect_item.setPos(0, current_y)
                rect_item.setBrush(QBrush(QColor("#e8e8e8")))
                rect_item.setPen(QPen(QColor("#cccccc"), 1))
                self.scene.addItem(rect_item)

                # テキスト
                text_item = QGraphicsSimpleTextItem(f"Page {page_idx + 1}")
                text_item.setBrush(QBrush(QColor("#999999")))
                # 中央寄せ
                text_w = text_item.boundingRect().width()
                text_h = text_item.boundingRect().height()
                text_item.setPos((w - text_w) / 2, current_y + (h - text_h) / 2)
                self.scene.addItem(text_item)

                # スロットに保存 (後で画像を重ねる)
                self.page_slots[(page_idx, rect_idx)] = (
                    rect_item,
                    text_item,
                    current_y,
                    w,
                    h,
                )

                current_y += h + spacing

        # シーンの範囲を確定
        self.scene.setSceneRect(
            self.scene.itemsBoundingRect().adjusted(-50, -50, 50, 50)
        )

        # 別スレッドでの実行準備
        # ここでは zoom_factor=1.0 で Worker に頼み、表示時に scale する
        self.thread = QThread()
        self.worker = PreviewWorker(pdf_path, crop_coordinates, scale_factor, 1.0)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.page_ready.connect(self._add_page_images)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _add_page_images(self, batch_data):
        """Workerから届いたバッチ（複数ページ分）の画像をシーン上のプレースホルダーの位置に配置する"""
        for page_idx, images in batch_data:
            for i, q_img in enumerate(images):
                if q_img is None:
                    continue

                # スロット情報を取得
                if (page_idx, i) not in self.page_slots:
                    continue
                    
                rect_item, text_item, y_pos, w, h = self.page_slots[(page_idx, i)]

                # 画像アイテムの作成
                pixmap = QPixmap.fromImage(q_img)
                pix_item = QGraphicsPixmapItem(pixmap)
                pix_item.setPos(0, y_pos)
                pix_item.setTransformationMode(Qt.SmoothTransformation)
                
                # 白い背景（枠線用）を後ろに引く
                bg_rect = QGraphicsRectItem(0, y_pos, w, h)
                bg_rect.setBrush(QBrush(Qt.white))
                bg_rect.setPen(QPen(QColor("#cccccc"), 1))
                self.scene.addItem(bg_rect)
                
                self.scene.addItem(pix_item)
                
                # プレースホルダーを隠す
                rect_item.setVisible(False)
                text_item.setVisible(False)
                
                # ズーム等での再利用（現在は transform ズームだが、互換性のために保持）
                self.preview_items.append(pix_item)
