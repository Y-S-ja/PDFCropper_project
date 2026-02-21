import fitz
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QListWidget, QGroupBox, QFormLayout, 
    QDoubleSpinBox, QListWidgetItem, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, Signal, QPointF, QRectF
from PySide6.QtGui import QImage, QPixmap

class PropertyPanel(QWidget):
    """QDockWidgetの中身として動作するプロパティ編集パネル"""
    orderChanged = Signal(list) # 並び順変更をメインウィンドウに知らせる用

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_item = None
        self._updating = False # ループ防止
        self.init_ui()
        self.connnectedRect = Qt.UserRole
        self.RECT_NUM = Qt.UserRole + 1

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 1. 枠一覧リスト
        self.list_label = QLabel("切り抜き枠一覧 (ドラッグで順序変更)")
        layout.addWidget(self.list_label)
        self.list_widget = QListWidget()
        
        # ドラッグ＆ドロップによる並び替えを有効化
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
        
        layout.addWidget(self.list_widget)

        # 2. 座標設定グループ
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

        # イベント接続
        self.list_widget.currentItemChanged.connect(self._on_list_selection_changed)
        for spin in [self.spin_x, self.spin_y, self.spin_w, self.spin_h]:
            spin.valueChanged.connect(self.apply_changes)

        self.setEnabled(False)

    def create_spin(self):
        spin = QDoubleSpinBox()
        spin.setRange(-99999, 99999)
        spin.setDecimals(1)
        spin.setSingleStep(1.0)
        return spin
        
    def update_list(self, rects):
        """ビュー内の枠リストを反映する"""
        if self._updating: return
        self._updating = True
        self.list_widget.clear()
        for i, rect in enumerate(rects):
            item = QListWidgetItem(f"枠 {rect.data(self.RECT_NUM)}")
            item.setData(self.connnectedRect, rect) # アイテムに実際のオブジェクトを紐付ける
            self.list_widget.addItem(item)
        self._updating = False
        # 現在の選択状態も同期させる
        self.sync_list_selection()

    def _on_rows_moved(self, parent, start, end, destination, row):
        """ドラッグで順番が入れ替わったら、新しいオブジェクトリストを通知する"""
        if self._updating: return
        
        new_order = []
        for i in range(self.list_widget.count()):
            list_item = self.list_widget.item(i)
            new_order.append(list_item.data(self.connnectedRect))
        
        self.orderChanged.emit(new_order)

    def _on_list_selection_changed(self, current, previous):
        """リストの選択が変更されたら、即座にパネルを更新し、シーン上のアイテムも選択する"""
        if self._updating or not current:
            return
            
        target_rect = current.data(self.connnectedRect)
        if target_rect:
            # 1. シグナルを待たずに即座にプロパティ値を反映
            self.set_target(target_rect)
            
            # 2. シーン側の選択も合わせる
            if target_rect.scene():
                if not target_rect.isSelected():
                    target_rect.scene().clearSelection()
                    target_rect.setSelected(True)

    def set_target(self, item):
        """編集対象のアイテムをセットし、現在の値をスピンボックスに反映"""
        if self.current_item != item:
            self.current_item = item
            self.sync_list_selection() 
        
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

    def sync_list_selection(self):
        """シーンの選択状態をリストのハイライトに同期させる"""
        if self._updating: return
        self._updating = True
        self.list_widget.clearSelection()
        if self.current_item:
            for i in range(self.list_widget.count()):
                list_item = self.list_widget.item(i)
                if list_item.data(self.connnectedRect) == self.current_item:
                    list_item.setSelected(True)
                    self.list_widget.setCurrentItem(list_item)
                    break
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


class PreviewPanel(QWidget):
    """切り抜かれた状態の画像を一覧表示するパネル"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()
        self.RECT_NUM = Qt.UserRole + 1

    def init_ui(self):
        layout = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll)

    def update_previews(self, view):
        """指定されたビューの枠に基づいてプレビュー画像を生成し、表示を更新する"""
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        
        if not view or not view.pdf_doc or not view.rects: return

        page = view.pdf_doc[0] 
        f = view.scale_factor
        for box in view.rects:
            rect = box.mapToScene(box.rect()).boundingRect()
            # 画面上の座標(ピクセル)をPDFの座標(ポイント)に変換
            fitz_rect = fitz.Rect(rect.left()*f, rect.top()*f, rect.right()*f, rect.bottom()*f)
            if fitz_rect.is_empty: continue
            
            pix = page.get_pixmap(clip=fitz_rect, matrix=fitz.Matrix(2, 2))
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
            
            item_widget = QWidget()
            item_vbox = QVBoxLayout(item_widget)
            
            label_title = QLabel(f"枠 {box.data(self.RECT_NUM)}")
            label_title.setStyleSheet("font-weight: bold;")
            item_vbox.addWidget(label_title)
            
            label_img = QLabel()
            full_pix = QPixmap.fromImage(img)
            label_img._full_pix = full_pix # 高解像度版をキャッシュしておく
            label_img.setPixmap(full_pix.scaledToWidth(max(50, self.width()-40), Qt.SmoothTransformation))
            item_vbox.addWidget(label_img)
            
            line = QFrame(); line.setFrameShape(QFrame.HLine); line.setFrameShadow(QFrame.Sunken)
            item_vbox.addWidget(line)
            self.container_layout.addWidget(item_widget)

    def resizeEvent(self, event):
        """ドックの幅が変わった際に、表示中のプレビュー画像をリサイズして追従させる"""
        super().resizeEvent(event)
        
        # コンテナ内の各アイテム（QLabel）を探してリサイズする
        # PDFからの再生成は重いため、保持しているQPixmapをスケーリングするだけに留める
        new_width = max(50, self.width() - 40)
        
        for i in range(self.container_layout.count()):
            item = self.container_layout.itemAt(i)
            widget = item.widget()
            if widget:
                # 子要素の中から画像を保持しているラベルを探す
                for label in widget.findChildren(QLabel):
                    if hasattr(label, "_full_pix"):
                        scaled_pix = label._full_pix.scaledToWidth(new_width, Qt.SmoothTransformation)
                        label.setPixmap(scaled_pix)
