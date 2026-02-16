import sys
import os
import fitz
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsPixmapItem, QGraphicsSimpleTextItem,
    QGraphicsItem
)
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QPixmap, QImage, QPen, QColor, QBrush
from ignore.cropbox import *

class PdfGraphicsView(QGraphicsView):
    fileDropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True) # ドロップを受け入れるように変更
        # 1. シーン（キャンバス）を作成
        self.setBackgroundBrush(QBrush(QColor("lightgray")))
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        
        # 2. 【魔法の設定】ズーム時の基準点を「マウスカーソルの下」にする
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        # ドラッグでスクロールできるようにする設定をオフ（最初は普通のカーソルにする）
        self.setDragMode(QGraphicsView.NoDrag)
        # ビューポートのカーソルを十字（範囲選択っぽく）または標準に設定
        self.viewport().setCursor(Qt.CrossCursor)
        
        self.pdf_item = None      # PDF画像
        self.current_rect = None  # ドラッグ中の枠
        self.rects = []           # 確定した枠（QGraphicsRectItem）のリスト
        self.start_pos = None

        self.badge_size = 24
        self.canvas_rect = QRectF(0, 0, 800, 600)
        self.scene.setSceneRect(self.canvas_rect)
        
        # 初期メッセージを表示
        self.show_intro_message()

    def update_scene_limit(self):
        """キャンバス領域を更新。force_physical=Trueの場合のみ、物理的な座標壁(sceneRect)を書き換える"""
        print("update_scene_limit")
        items_rect = self.scene.itemsBoundingRect()
        if items_rect.isNull():
            self.canvas_rect = QRectF(0, 0, 800, 600)
        else:
            margin = 1000
            self.canvas_rect = items_rect.adjusted(-margin, -margin, margin, margin)
            print("adjusted")
        self.scene.setSceneRect(self.canvas_rect)
    
    def drawForeground(self, painter, rect):
        """キャンバス領域（canvas_rect）に枠線を描画"""
        if hasattr(self, "canvas_rect") and not self.canvas_rect.isNull():
            pen = QPen(QColor(150, 150, 150), 1.5, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.canvas_rect)

    def show_intro_message(self):
        """起動時のメッセージを表示"""
        self.scene.clear()
        text = self.scene.addSimpleText("PDFファイルをここにドラッグ＆ドロップしてください")
        text.setBrush(QBrush(QColor("gray")))
        font = text.font()
        font.setPointSize(18)
        text.setFont(font)
        
        # 中央寄せ
        r = text.boundingRect()
        text.setPos((self.canvas_rect.width() - r.width())/2, (self.canvas_rect.height() - r.height())/2)

    def load_pdf_page(self, file_path):
        if not os.path.exists(file_path):
            print(f"❌ ファイルが見つかりません: {file_path}")
            return
        
        # 前の画像や枠をクリア
        self.scene.clear()
        self.rects = []
        
        # PDF読み込み（高解像度で1回だけ作る）
        doc = fitz.open(file_path)
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(3, 3)) # 3倍高画質
        img_data = pix.tobytes("png")
        pixmap = QPixmap.fromImage(QImage.fromData(img_data))
        
        # 3. シーンに画像を追加
        self.pdf_item = self.scene.addPixmap(pixmap)
        
        # PDF本来のサイズとの比率を計算（これが唯一の計算）
        self.scale_factor = page.rect.width / pixmap.width()

        # 最初の表示を小さくする（0.4倍）
        self.resetTransform()
        self.scale(0.4, 0.4)

        self.update_scene_limit()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    super().dragEnterEvent(event)
                    return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    # super().dragMoveEvent(event)
                    return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith(".pdf"):
                self.fileDropped.emit(file_path)
                break

    # def dragLeaveEvent(self, event):
    #     # [追加] 出ていく時も親クラスに教えてあげる
    #     super().dragLeaveEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() == Qt.ControlModifier:
            # 4. 【ズーム機能】たったこれだけ！
            # 画像をリサイズするのではなく、ビューの「倍率」を変える
            angle = event.angleDelta().y()
            factor = 1.2 if angle > 0 else 0.8
            self.scale(factor, factor)
            event.accept()
        else:
            super().wheelEvent(event)

    # --- 範囲選択のロジック ---
    def mousePressEvent(self, event):
        # 右クリックなら削除判定
        if event.button() == Qt.RightButton:
            item = self.itemAt(event.position().toPoint())
            if item:
                # バッジやテキストをクリックした可能性も考慮して親を辿る
                target = item
                while target and target.data(0) != "selection_rect":
                    target = target.parentItem()
                
                if target in self.rects:
                    self.rects.remove(target)
                    self.scene.removeItem(target)
                    self.update_numbers() # 番号を詰め直す
                    return # イベント終了
        
        if event.button() == Qt.LeftButton:
            # シーン上の座標（画像上の絶対位置）を取得
            self.start_pos = self.mapToScene(event.position().toPoint())
            
            # 枠を作成してシーンに追加
            self.current_rect = myCropBox(QRectF(self.start_pos, self.start_pos))
            self.scene.addItem(self.current_rect)
            
            # ドラッグモードを一時オフ（範囲選択と干渉しないように）
            self.setDragMode(QGraphicsView.NoDrag)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.start_pos and self.current_rect:
            # 現在のマウス位置（シーン座標）
            current_pos = self.mapToScene(event.position().toPoint())
            
            # 四角形の形を更新
            rect = QRectF(self.start_pos, current_pos).normalized()
            self.current_rect.setRect(rect)
        super().mouseMoveEvent(event)
    
    # 中央寄せの簡易計算
    def centerBadge(self, text):
        brect = text.boundingRect()
        text.setPos((self.badge_size - brect.width())/2, (self.badge_size - brect.height())/2)

    def mouseReleaseEvent(self, event):
        if self.start_pos and self.current_rect:
            rect = self.current_rect.rect()
            
            # 【重要】小さすぎる枠（クリックミス等）は無視して削除する
            if rect.width() < 5 or rect.height() < 5:
                self.scene.removeItem(self.current_rect)
            else:
                # 確定したらリストに入れて、色は青に変える
                self.current_rect.setPen(QPen(QColor(0, 120, 215), 2))
                self.current_rect.setBrush(QBrush(QColor(0, 120, 215, 40)))
                
                # 識別タグを追加（削除時にこれを目印にする）
                self.current_rect.setData(0, "selection_rect")
                
                # --- 番号表示 ---
                index = len(self.rects) + 1
                
                # 親を current_rect にすることで、枠と一緒に移動・削除される
                badge = QGraphicsRectItem(0, 0, self.badge_size, self.badge_size, parent=self.current_rect)
                badge.setBrush(QBrush(QColor(0, 120, 215)))
                badge.setPen(Qt.NoPen)
                badge.setPos(rect.topLeft())
                # ズームしても大きさが変わらないように設定
                badge.setFlag(QGraphicsItem.ItemIgnoresTransformations)
                
                text = QGraphicsSimpleTextItem(str(index), parent=badge)
                text.setBrush(QBrush(Qt.white))
                # 中央寄せの簡易計算
                self.centerBadge(text)
                
                # 枠オブジェクトそのものをリストに保存
                self.rects.append(self.current_rect)
            
            self.start_pos = None
            self.current_rect = None
            self.setDragMode(QGraphicsView.NoDrag) # 手の形に戻さない
        self.update_scene_limit()
        super().mouseReleaseEvent(event)

    def update_numbers(self):
        """残っている枠の番号を1から順に振り直す"""
        for i, item in enumerate(self.rects):
            # 子要素（バッジの枠 -> テキスト）を辿って文字を更新
            for child in item.childItems():
                # QGraphicsRectItem かつ親が自分（item）ならバッジ
                if isinstance(child, QGraphicsRectItem):
                    for grandchild in child.childItems():
                        if isinstance(grandchild, QGraphicsSimpleTextItem):
                            grandchild.setText(str(i + 1))
                            # 中央寄せ再計算
                            self.centerBadge(grandchild)

    def clear_selections(self):
        # シーン内の "selection_rect" タグが付いたアイテムだけを削除
        for item in list(self.scene.items()):
            if item.data(0) == "selection_rect":
                self.scene.removeItem(item)
        # データリストもクリア
        self.rects = []
        self.current_rect = None

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QGraphicsView PDFツール")
        self.resize(1000, 800)

        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("ファイル")

        self.view = PdfGraphicsView()
        self.setAcceptDrops(True) # ドラッグ＆ドロップを許可

        self.crop_btn = QPushButton("切り抜いて保存")
        self.crop_btn.clicked.connect(self.process_crop)

        self.clear_btn = QPushButton("選択範囲をクリア")
        self.clear_btn.clicked.connect(self.view.clear_selections)
        
        self.view.fileDropped.connect(self.load_new_pdf) # 追加：Viewへのドロップを接続

        btn_layout = QHBoxLayout() # ボタンを横に並べる
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addWidget(self.crop_btn)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("左ドラッグ: 範囲選択 / 右ドラッグ: 移動 / Ctrl+ホイール: ズーム"))
        layout.addLayout(btn_layout)
        layout.addWidget(self.view)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.target_pdf = None

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            # 渡されたURL（ファイルパス）がPDFかどうかをチェック
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    return

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith(".pdf"):
                self.load_new_pdf(file_path)
                break

    def load_new_pdf(self, file_path):
        self.target_pdf = file_path
        self.view.load_pdf_page(file_path)
        # ウィンドウタイトルにファイル名を表示
        self.setWindowTitle(f"QGraphicsView PDFツール - {os.path.basename(file_path)}")

    def process_crop(self):
        if not self.target_pdf:
            QMessageBox.warning(self, "エラー", "PDFファイルが読み込まれていません")
            return
        if not self.view.rects:
            # メッセージボックスが小さすぎてタイトルが見切れるのを防ぐため、
            # インスタンス化して幅を確保するか、スペースを追加する
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("警告")
            msg.setText("範囲を選択してください" + " " * 15) # スペースで幅を確保
            # msg.setStyleSheet("QLabel{min-width: 100px;}")
            msg.exec()
            return
            
        base, ext = os.path.splitext(os.path.basename(self.target_pdf))
        default_name = f"{base}_cropped{ext}"
        output_path, _ = QFileDialog.getSaveFileName(self, "保存", default_name, "PDF Files (*.pdf)")
        if not output_path: return

        try:
            f = self.view.scale_factor
            src_doc = fitz.open(self.target_pdf)
            new_doc = fitz.open()

            for page_index in range(len(src_doc)):
                for item in self.view.rects:
                    rect = item.rect() # アイテムから座標を取得
                    new_doc.insert_pdf(src_doc, from_page=page_index, to_page=page_index)
                    # RectFの座標をPDF座標に変換
                    pdf_rect = fitz.Rect(rect.left()*f, rect.top()*f, rect.right()*f, rect.bottom()*f)
                    new_doc[-1].set_cropbox(pdf_rect)

            new_doc.save(output_path)
            new_doc.close()
            src_doc.close()
            QMessageBox.information(self, "完了", "保存しました")
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))

app = QApplication(sys.argv)
window = MainWindow()
window.show()
sys.exit(app.exec())