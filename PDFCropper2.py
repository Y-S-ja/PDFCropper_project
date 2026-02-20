import sys
import os
import fitz
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsPixmapItem, QGraphicsSimpleTextItem,
    QGraphicsItem, QTabWidget, QDockWidget, QDoubleSpinBox, QFormLayout, QGroupBox
)
from PySide6.QtCore import Qt, QRectF, Signal, QPointF
from PySide6.QtGui import QPixmap, QImage, QPen, QColor, QBrush
from myModule import *

class PdfGraphicsView(QGraphicsView):
    fileDropped = Signal(str)
    selectionChanged = Signal(object) # 選択されたアイテム(myCropBox)を通知用

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True) # ドロップを受け入れるように変更
        # 1. シーン（キャンバス）を作成
        self.setBackgroundBrush(QBrush(QColor("lightgray")))
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.scene.selectionChanged.connect(self._on_scene_selection_changed)
        
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

        self.field_rect = QGraphicsRectItem(QRectF(0, 0, 800, 600))
        self.field_rect.setPos(0, 0)
        self.scene.addItem(self.field_rect)
        
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
        
        self.scene.setSceneRect(self.canvas_rect)
    
    def drawForeground(self, painter, rect):
        """キャンバス領域（canvas_rect）に枠線を描画"""
        if hasattr(self, "canvas_rect") and not self.canvas_rect.isNull():
            pen = QPen(QColor(150, 150, 150), 1.5, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.canvas_rect)
    
    def center_A_on_B(self, A, B):
        br = A.boundingRect()
        A.setPos((B.rect().width() - br.width())/2, (B.rect().height() - br.height())/2)

    def show_intro_message(self):
        """起動時のメッセージを表示"""
        # self.scene.clear()
        text = self.scene.addSimpleText("PDFファイルをここにドラッグ＆ドロップしてください")
        text.setBrush(QBrush(QColor("gray")))
        font = text.font()
        font.setPointSize(18)
        text.setFont(font)
        # 案内テキストであることを識別するためのタグを付ける
        text.setData(self.TAG_NAME, "intro_text")
        self.center_A_on_B(text, self.field_rect)

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
            # いったん選択を解除する（背景クリックで解除するため）
            self.scene.clearSelection()
            self.start_pos = self.mapToScene(event.position().toPoint())
            
            if target_cropbox:
                print("Left-clicked: CropBox (Resizing/Moving)")
                self.new_rect = None
                super().mousePressEvent(event)
            elif is_intro_text:
                print("Left-clicked: Intro Text (Ignoring)")
            else:
                # 新規作成：pos を開始位置にし、rect は (0,0) で初期化
                print(f"Left-clicked: Background (Creating new box)")
                self.new_rect = myCropBox(QRectF(0, 0, 0, 0))
                self.new_rect.setPos(self.start_pos)
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
                badge = myBadge(index, self.badge_size, parent=self.new_rect)
                badge.setPos(rect.topLeft())
                
                self.rects.append(self.new_rect)
                # 新しく作った枠を選択状態にする（プロパティパネルに即反映される）
                self.scene.clearSelection()
                self.new_rect.setSelected(True)
            
            self.start_pos = None
            self.new_rect = None
        
        super().mouseReleaseEvent(event)
        self.update_scene_limit()

    def update_numbers(self):
        """残っている枠の番号を1から順に振り直す"""
        for i, item in enumerate(self.rects):
            # 子要素から myBadge を探して更新
            for child in item.childItems():
                if isinstance(child, myBadge):
                    child.set_number(i + 1)

    def _on_scene_selection_changed(self):
        """シーンの選択が変更されたら、選択中の myCropBox をシグナルで飛ばす"""
        items = self.scene.selectedItems()
        target = None
        if items and isinstance(items[0], myCropBox):
            target = items[0]
        self.selectionChanged.emit(target)

    def clear_selections(self):
        # シーン内の "selection_rect" タグが付いたアイテムだけを削除
        for item in list(self.scene.items()):
            if item.data(self.TAG_NAME) == "selection_rect":
                self.scene.removeItem(item)
        # データリストもクリア
        self.rects = []
        self.new_rect = None
        self.update_scene_limit()
        # プロパティパネル側でも再描画を促すために選択状態をリセット
        self._on_scene_selection_changed()

class PropertyPanel(QWidget):
    """QDockWidgetの中身として動作するプロパティ編集パネル"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_item = None
        self._updating = False # ループ防止
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        group = QGroupBox("座標・サイズ設定 (px)")
        form = QFormLayout(group)

        self.spin_x = self.create_spin()
        self.spin_y = self.create_spin()
        self.spin_w = self.create_spin()
        self.spin_h = self.create_spin()

        form.addRow("X:", self.spin_x)
        form.addRow("Y:", self.spin_y)
        form.addRow("幅:", self.spin_w)
        form.addRow("高さ:", self.spin_h)

        layout.addWidget(group)
        layout.addStretch()

        # 値が変更された時の接続
        for spin in [self.spin_x, self.spin_y, self.spin_w, self.spin_h]:
            spin.valueChanged.connect(self.apply_changes)

        self.setEnabled(False)

    def create_spin(self):
        spin = QDoubleSpinBox()
        spin.setRange(-99999, 99999)
        spin.setDecimals(1)
        spin.setSingleStep(1.0)
        return spin

    def set_target(self, item):
        """編集対象のアイテムをセットし、現在の値をスピンボックスに反映"""
        self.current_item = item
        if not item:
            self.setEnabled(False)
            return

        self._updating = True
        self.setEnabled(True)
        rect = item.rect()
        pos = item.pos()
        self.spin_x.setValue(pos.x())
        self.spin_y.setValue(pos.y())
        self.spin_w.setValue(rect.width())
        self.spin_h.setValue(rect.height())
        self._updating = False

    def apply_changes(self):
        """スピンボックスの値をアイテムに反映"""
        if not self.current_item or self._updating:
            return
        
        # アイテムの座標系に合わせて更新
        new_pos = QPointF(self.spin_x.value(), self.spin_y.value())
        new_rect = QRectF(0, 0, self.spin_w.value(), self.spin_h.value())
        
        self.current_item.setPos(new_pos)
        self.current_item.setRect(new_rect)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDFCropper2")
        self.resize(1000, 800)
        self.setAcceptDrops(True) # ドラッグ＆ドロップを許可

        # カスタムメニューバーを使用
        # self.setMenuBar(HoverMenuBar(self))
        menu_bar = self.menuBar()

        # ファイルメニュー
        file_menu = menu_bar.addMenu("ファイル")
        
        open_action = file_menu.addAction("PDFを開く")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_file)
        
        add_tab_action = file_menu.addAction("タブを追加")
        add_tab_action.setShortcut("Ctrl+T")
        add_tab_action.triggered.connect(self.add_new_tab)
        
        save_action = file_menu.addAction("保存")
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.process_crop)
        
        close_tab_action = file_menu.addAction("タブを閉じる")
        close_tab_action.setShortcut("Ctrl+W")
        close_tab_action.triggered.connect(self.close_current_tab)

        file_menu.addSeparator()
        exit_action = file_menu.addAction("終了")
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)

        # 編集メニュー
        edit_menu = menu_bar.addMenu("編集")
        clear_action = edit_menu.addAction("選択範囲をクリア")
        clear_action.setShortcut("Ctrl+Shift+X")
        clear_action.triggered.connect(lambda: self.current_view().clear_selections() if self.current_view() else None)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.remove_tab)
        # タブ切り替え時にタイトルとプロパティの接続を更新
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tab_widget)
        
        self.target_pdfs = {} # タブごとのパスを管理 {view_object: path}
        
        # ドックウィジェット（右側）を追加
        self.dock = QDockWidget("プロパティ", self)
        self.dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        
        # プロパティパネルを作成してドックにセット
        self.prop_panel = PropertyPanel()
        self.dock.setWidget(self.prop_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)

        # 表示メニュー
        view_menu = menu_bar.addMenu("表示")
        view_menu.addAction(self.dock.toggleViewAction())

        # 最初のタブを追加
        self.add_new_tab()

    def _on_tab_changed(self, index):
        """タブが切り替わったら、現在のビューの選択状態をパネルに繋ぎ変える"""
        self.update_window_title()
        view = self.current_view()
        if view:
            # ビューのシグナルをパネルに接続
            # 特定の接続先(slot)を指定して解除することで、未接続時の警告を回避
            try: view.selectionChanged.disconnect(self.prop_panel.set_target)
            except: pass
            view.selectionChanged.connect(self.prop_panel.set_target)
            
            # ビュー側のメソッドを呼んで現在の選択状態をパネルに通知
            view._on_scene_selection_changed()
        else:
            self.prop_panel.set_target(None)


    def current_view(self):
        """現在のアクティブなタブにあるビューを返す"""
        return self.tab_widget.currentWidget()

    def add_new_tab(self):
        """新しいタブを追加する。空いている最小の番号を割り振る"""
        # 現在使用されている「無題 X」の番号をすべて取得
        used_numbers = set()
        for i in range(self.tab_widget.count()):
            text = self.tab_widget.tabText(i)
            if text.startswith("無題 "):
                try:
                    num = int(text.split(" ")[1])
                    used_numbers.add(num)
                except (IndexError, ValueError):
                    pass
        
        # 1から順に確認して空いている最小の番号を探す
        new_num = 1
        while new_num in used_numbers:
            new_num += 1
            
        new_view = PdfGraphicsView()
        new_view.fileDropped.connect(self.load_new_pdf)
        index = self.tab_widget.addTab(new_view, f"無題 {new_num}")
        self.tab_widget.setCurrentIndex(index)
        self.update_window_title()
        return new_view

    def update_window_title(self):
        """現在のタブの名前に基づいてウィンドウタイトルを更新する"""
        index = self.tab_widget.currentIndex()
        if index != -1:
            tab_text = self.tab_widget.tabText(index)
            self.setWindowTitle(f"PDFCropper2 - {tab_text}")
        else:
            self.setWindowTitle("PDFCropper2")

    def close_current_tab(self):
        """現在のタブを閉じる"""
        current_index = self.tab_widget.currentIndex()
        if current_index != -1:
            self.remove_tab(current_index)

    def remove_tab(self, index):
        """指定したインデックスのタブを閉じる"""
        widget = self.tab_widget.widget(index)
        if widget in self.target_pdfs:
            del self.target_pdfs[widget]
        self.tab_widget.removeTab(index)
        
        # 全てのタブが閉じられたら新しい空のタブを作る
        if self.tab_widget.count() == 0:
            self.add_new_tab()

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "PDFを開く", "", "PDF Files (*.pdf)")
        if file_path:
            self.load_new_pdf(file_path)

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
        view = self.current_view()
        if not view: return
        
        self.target_pdfs[view] = file_path
        view.load_pdf_page(file_path)
        # タブの名前をファイル名に変える
        current_index = self.tab_widget.currentIndex()
        self.tab_widget.setTabText(current_index, os.path.basename(file_path))
        # ウィンドウタイトルも更新
        self.update_window_title()

    def process_crop(self):
        view = self.current_view()
        target_pdf = self.target_pdfs.get(view)
        
        if not target_pdf:
            QMessageBox.warning(self, "エラー", "PDFファイルが読み込まれていません")
            return
        if not view.rects:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("警告")
            msg.setText("範囲を選択してください" + " " * 15)
            msg.exec()
            return
            
        base, ext = os.path.splitext(os.path.basename(target_pdf))
        default_name = f"{base}_cropped{ext}"
        output_path, _ = QFileDialog.getSaveFileName(self, "保存", default_name, "PDF Files (*.pdf)")
        if not output_path: 
            print("QFileDialog.getSaveFileName() returned empty path")
            return

        try:
            f = view.scale_factor
            src_doc = fitz.open(target_pdf)
            new_doc = fitz.open()

            for page_index in range(len(src_doc)):
                for item in view.rects:
                    # ハンドルを含まない、純粋な枠の範囲(rect)をシーン座標に変換する
                    s_rect = item.mapToScene(item.rect()).boundingRect()
                    
                    new_doc.insert_pdf(src_doc, from_page=page_index, to_page=page_index)
                    # シーン座標をPDFのピクセル座標に変換
                    pdf_rect = fitz.Rect(s_rect.left()*f, s_rect.top()*f, s_rect.right()*f, s_rect.bottom()*f)
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