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
from cropbox import *

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
        # キャンバスが画面より小さい時に中央に寄せる設定
        self.setAlignment(Qt.AlignCenter)
        
        # ドラッグでスクロールできるようにする設定をオフ（最初は普通のカーソルにする）
        self.setDragMode(QGraphicsView.NoDrag)
        # ビューポートのカーソルを十字（範囲選択っぽく）または標準に設定
        self.viewport().setCursor(Qt.CrossCursor)
        
        self.pdf_item = None      # PDF画像
        self.new_rect = None  # ドラッグ中の枠
        self.rects = []           # 確定した枠（QGraphicsRectItem）のリスト
        self.start_pos = None
        self.TAG_NAME = 0

        self.badge_size = 24
        self.canvas_rect = QRectF(0, 0, 800, 600)
        self.scene.setSceneRect(self.canvas_rect)
        
        # 初期メッセージを表示
        self.show_intro_message()

    def detectItemByTag(self, tag):
        for item in self.scene.items():
            if item.data(self.TAG_NAME) == tag:
                return item
        return None

    def update_scene_limit(self):
        """キャンバス領域を更新。force_physical=Trueの場合のみ、物理的な座標壁(sceneRect)を書き換える"""
        # print("update_scene_limit")
        items_rect = self.scene.itemsBoundingRect()
        if items_rect.isNull():
            # print("line 48, items_rect is null")
            self.canvas_rect = QRectF(0, 0, 800, 600)
        else:
            margin = 500
            self.canvas_rect = items_rect.adjusted(-margin, -margin, margin, margin)
            # print("line 53, adjusted")
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
        # 案内テキストであることを識別するためのタグを付ける
        text.setData(self.TAG_NAME, "intro_text")
        
        # 中央寄せ
        r = text.boundingRect()
        text.setPos((self.canvas_rect.width() - r.width())/2, (self.canvas_rect.height() - r.height())/2)

        self.update_scene_limit()

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
        # 読み込み直後に、ビューの中心をキャンバスの中央に合わせる
        self.centerOn(self.scene.itemsBoundingRect().center())

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
            # 現在のズーム倍率を取得 (m11 は X方向のスケール)
            current_scale = self.transform().m11()
            
            angle = event.angleDelta().y()
            factor = 1.2 if angle > 0 else 0.8
            
            # ズーム後の倍率を計算
            new_scale = current_scale * factor
            
            # --- 倍率制限 (0.1倍 〜 2.0倍) ---
            if 0.1 <= new_scale <= 2.0:
                self.scale(factor, factor)
            
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        
        # --- 判定フェーズ：クリックされたものが何かを特定する ---
        target_cropbox = None
        is_intro_text = False
        
        temp = item
        while temp:
            if isinstance(temp, myCropBox):
                target_cropbox = temp
                break
            if temp.data(self.TAG_NAME) == "intro_text":
                is_intro_text = True
                break
            temp = temp.parentItem()
        
        # --- 右クリック：削除 ---
        if event.button() == Qt.RightButton:
            if target_cropbox and target_cropbox in self.rects:
                print("Right-clicked: CropBox (Deleting)")
                self.rects.remove(target_cropbox)
                self.scene.removeItem(target_cropbox)
                self.update_numbers()
                return
            elif is_intro_text:
                print("Right-clicked: Intro Text (Ignoring)")
            else:
                print(f"Right-clicked: Background (item={item})")
            super().mousePressEvent(event)

        # --- 左クリック：操作 or 新規作成 ---
        elif event.button() == Qt.LeftButton:
            self.start_pos = self.mapToScene(event.position().toPoint())
            
            if target_cropbox:
                print("Left-clicked: CropBox (Resizing/Moving)")
                self.new_rect = None
                super().mousePressEvent(event)
            elif is_intro_text:
                print("Left-clicked: Intro Text (Ignoring)")
            else:
                # 何もない場所なら新規作成
                print(f"Left-clicked: Background (Creating new box, item={item})")
                self.new_rect = myCropBox(QRectF(self.start_pos, self.start_pos))
                self.scene.addItem(self.new_rect)
        
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.start_pos and self.new_rect:
            # 新規枠作成
            # 現在のマウス位置（シーン座標）
            current_pos = self.mapToScene(event.position().toPoint())
            
            # 開始点からの差分でローカルの rect を計算
            diff = current_pos - self.start_pos
            rect = QRectF(0, 0, diff.x(), diff.y()).normalized()
            
            # もしマイナス方向にドラッグしたら、posの方を調整する（常に左上が基点になるように）
            actual_top_left = QPointF(
                min(self.start_pos.x(), current_pos.x()),
                min(self.start_pos.y(), current_pos.y())
            )
            self.new_rect.setPos(actual_top_left)
            self.new_rect.setRect(QRectF(0, 0, abs(diff.x()), abs(diff.y())))
        else:
            # 移動と変形
            super().mouseMoveEvent(event)
            target = self.detectItemByTag("selection_rect")
            # if target:
                # print(f"line 267, self.cropbox pos: {target.pos()}")
    
    # 中央寄せの簡易計算
    def centerBadge(self, text):
        brect = text.boundingRect()
        text.setPos((self.badge_size - brect.width())/2, (self.badge_size - brect.height())/2)

    def mouseReleaseEvent(self, event):
        if self.start_pos and self.new_rect:
            # 新規枠作成
            rect = self.new_rect.rect()
            
            # 【重要】小さすぎる枠（クリックミス等）は無視して削除する
            if rect.width() < 5 or rect.height() < 5:
                self.scene.removeItem(self.new_rect)
            else:
                # 確定したらリストに入れて、色は青に変える
                pen = QPen(QColor(0, 120, 215), 3)
                pen.setCosmetic(True) # ズームしても太さが変わらない設定
                self.new_rect.setPen(pen)
                self.new_rect.setBrush(QBrush(QColor(0, 120, 215, 40)))
                
                # 識別タグを追加（削除時にこれを目印にする）
                self.new_rect.setData(0, "selection_rect")
                
                # --- 番号表示 ---
                index = len(self.rects) + 1
                
                # 親を new_rect にすることで、枠と一緒に移動・削除される
                badge = QGraphicsRectItem(0, 0, self.badge_size, self.badge_size, parent=self.new_rect)
                badge.setBrush(QBrush(QColor(0, 120, 215)))
                badge.setPen(Qt.NoPen)
                badge.setPos(rect.topLeft())
                # ズームしても大きさが変わらないように設定
                badge.setFlag(QGraphicsItem.ItemIgnoresTransformations)
                
                text = QGraphicsSimpleTextItem(str(index), parent=badge)
                text.setBrush(QBrush(Qt.white))
                # 中央寄せの簡易計算
                self.centerBadge(text)
                
                self.rects.append(self.new_rect)
            
            self.start_pos = None
            self.new_rect = None
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
            if item.data(self.TAG_NAME) == "selection_rect":
                self.scene.removeItem(item)
        # データリストもクリア
        self.rects = []
        self.new_rect = None

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