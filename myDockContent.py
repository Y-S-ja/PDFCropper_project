from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QGroupBox,
    QFormLayout,
    QDoubleSpinBox,
    QListWidgetItem,
    QScrollArea,
    QFrame,
    QCheckBox,
    QPushButton,
    QMenu,
)
from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QTimer, QCoreApplication
from PySide6.QtGui import QPixmap
from pdf_processor import PdfProcessor
from myModule import myCropBox
from workspace_models import (
    AssetManager,
    SourceAsset,
    CroppedAsset,
    JoinedAsset,
    WorkspaceAsset,
)


class PropertyPanel(QWidget):
    """QDockWidgetの中身として動作するプロパティ編集パネル"""

    orderChanged = Signal(list)  # 並び順変更をメインウィンドウに知らせる用
    syncSizeChanged = Signal(bool)  # サイズ同期のON/OFFを知らせる用
    syncSymmetryChanged = Signal(bool)  # 対称性同期のON/OFFを知らせる用

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_item = None
        self._updating = False  # ループ防止
        self.init_ui()
        self.connectedRectRole = (
            Qt.UserRole + 10
        )  # リストアイテム用の独自ロール (衝突回避)

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

        # 3. グループ同期設定
        sync_group = QGroupBox("テンプレート同期設定")
        sync_layout = QVBoxLayout(sync_group)
        self.check_sync_size = QCheckBox("サイズを共有")
        self.check_sync_symmetry = QCheckBox("対称性を維持 (2-in-1等)")

        sync_layout.addWidget(self.check_sync_size)
        sync_layout.addWidget(self.check_sync_symmetry)
        layout.addWidget(sync_group)

        layout.addStretch()

        # イベント接続
        self.list_widget.currentItemChanged.connect(self._on_list_selection_changed)
        for spin in [self.spin_x, self.spin_y, self.spin_w, self.spin_h]:
            spin.valueChanged.connect(self.apply_changes)

        self.check_sync_size.toggled.connect(self.syncSizeChanged.emit)
        self.check_sync_symmetry.toggled.connect(self.syncSymmetryChanged.emit)

        self.setEnabled(False)

    def create_spin(self):
        spin = QDoubleSpinBox()
        spin.setRange(-99999, 99999)
        spin.setDecimals(1)
        spin.setSingleStep(1.0)
        return spin

    def update_list(self, rects: list[myCropBox]):
        """ビュー内の枠リストを反映する"""
        if self._updating:
            return
        self._updating = True
        self.list_widget.clear()
        for i, rect in enumerate(rects):
            item = QListWidgetItem(f"枠 {rect.rect_id}")
            item.setData(
                self.connectedRectRole, rect
            )  # アイテムに実際のオブジェクトを紐付ける
            self.list_widget.addItem(item)
        self._updating = False
        # 現在の選択状態も同期させる
        self.sync_list_selection()

    def _on_rows_moved(self, parent, start, end, destination, row):
        """ドラッグで順番が入れ替わったら、新しいオブジェクトリストを通知する"""
        if self._updating:
            return

        new_order = []
        for i in range(self.list_widget.count()):
            list_item = self.list_widget.item(i)
            new_order.append(list_item.data(self.connectedRectRole))

        self.orderChanged.emit(new_order)

    def _on_list_selection_changed(self, current, previous):
        """リストの選択が変更されたら、即座にパネルを更新し、シーン上のアイテムも選択する"""
        if self._updating or not current:
            return

        target_rect = current.data(self.connectedRectRole)
        if target_rect:
            # 1. シグナルを待たずに即座にプロパティ値を反映
            self.set_target(target_rect)

            # 2. シーン側の選択も合わせる
            if target_rect.scene():
                if not target_rect.isSelected():
                    target_rect.scene().clearSelection()
                    target_rect.setSelected(True)

    def set_target(self, item: myCropBox):
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
        if self._updating:
            return
        self._updating = True
        self.list_widget.clearSelection()
        if self.current_item:
            for i in range(self.list_widget.count()):
                list_item = self.list_widget.item(i)
                if list_item.data(self.connectedRectRole) == self.current_item:
                    list_item.setSelected(True)
                    self.list_widget.setCurrentItem(list_item)
                    break
        self._updating = False

    def update_sync_settings(self, sync_size, sync_symmetry):
        """ビューから同期設定のフラグを受け取ってUIに反映する"""
        self._updating = True
        self.check_sync_size.setChecked(sync_size)
        self.check_sync_symmetry.setChecked(sync_symmetry)
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

        # リサイズイベントのデバウンス（遅延実行）用タイマー
        self.resize_timer = QTimer(self)
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self._do_delayed_resize)

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
        """
        指定されたビューの現在のページの枠に基づいてプレビュー画像を生成し、表示を更新する
        """
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not view or not view.pdf_path or not view.rects:
            return

        # 1. 座標だけのリストを作る
        crop_coordinates = []
        for box in view.rects:
            r = box.scene_rect
            crop_coordinates.append((r.left(), r.top(), r.right(), r.bottom()))

        # 2. 現在のページの画像を取得
        images = PdfProcessor.generate_page_preview(
            view.pdf_path, view.current_page_index, crop_coordinates, view.scale_factor
        )

        # 3. 各枠のプレビューを追加
        for i, q_img in enumerate(images):
            if q_img is None:
                continue

            rect_num = view.rects[i].rect_id

            # --- UI構築 (ラベルと画像) ---
            item_widget = QWidget()
            vbox = QVBoxLayout(item_widget)
            vbox.setContentsMargins(5, 5, 5, 5)

            label_title = QLabel(f"枠 {rect_num}")
            label_title.setStyleSheet("font-weight: bold;")
            vbox.addWidget(label_title)

            label_img = QLabel()
            # QImage をリサイズしてから QPixmap に変換
            scaled_q_img = q_img.scaledToWidth(
                max(50, self.width() - 40), Qt.SmoothTransformation
            )
            label_img.setPixmap(QPixmap.fromImage(scaled_q_img))

            # リサイズ用に元の QImage を保持
            label_img._full_pix = q_img
            vbox.addWidget(label_img)

            self.container_layout.addWidget(item_widget)

            # 1枚分の処理が終わるごとに表示させる。
            # 全体の処理が終わるのを待たない。
            # QThreadに変える
            QCoreApplication.processEvents()

    def resizeEvent(self, event):
        """ドックの幅が変わった際、即座にタイマーを回して変更終了を待つ"""
        super().resizeEvent(event)
        self.resize_timer.start(100)

    def _do_delayed_resize(self):
        """ドラッグが止まった後に一括で画像をリサイズする"""
        new_width = max(50, self.width() - 40)

        for i in range(self.container_layout.count()):
            item = self.container_layout.itemAt(i)
            widget = item.widget()
            if widget:
                # 子要素の中から画像を保持しているラベルを探す
                for label in widget.findChildren(QLabel):
                    if hasattr(label, "_full_pix"):
                        # label._full_pix は QImage
                        scaled_q_img = label._full_pix.scaledToWidth(
                            new_width, Qt.SmoothTransformation
                        )
                        label.setPixmap(QPixmap.fromImage(scaled_q_img))


class AssetShelfWidget(QFrame):
    """
    素材棚のUIを司るウィジェット
    """

    assetSelected = Signal(str)  # ダブルクリックされた素材IDを通知

    def __init__(self, asset_mgr: AssetManager):
        super().__init__()
        self.asset_mgr = asset_mgr
        self.show_hidden = False  # 現在非表示リストを見ているか

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)

        # 上部：切り替えボタン
        self.toggle_btn = QPushButton("👁 表示中の素材")
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self.on_toggle_view)
        self.layout.addWidget(self.toggle_btn)

        # リスト
        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.model().rowsMoved.connect(self.on_rows_moved)
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)
        self.layout.addWidget(self.list_widget)

        self.asset_mgr.assets_changed.connect(self.refresh_list)

    def on_toggle_view(self):
        self.show_hidden = self.toggle_btn.isChecked()
        if self.show_hidden:
            self.toggle_btn.setText("🚫 非表示アイテムを表示中")
            self.toggle_btn.setStyleSheet("background-color: #ff5722; color: white;")
        else:
            self.toggle_btn.setText("👁 表示中の素材")
            self.toggle_btn.setStyleSheet("")
        self.refresh_list()

    def refresh_list(self):
        self.list_widget.clear()
        for asset in self.asset_mgr.all_assets():
            # 表示フィルタ（通常時は visible=True のみ、トグル時は visible=False のみ）
            if asset.is_visible == (not self.show_hidden):
                icon = "📄" if isinstance(asset, SourceAsset) else "✂️"
                if isinstance(asset, JoinedAsset):
                    icon = "🔗"

                item = QListWidgetItem(f"{icon} {asset.name}")
                item.setData(Qt.UserRole, asset.id)
                self.list_widget.addItem(item)

    def on_rows_moved(self, parent, start, end, destination, row):
        # 内部的なドラッグ移動を AssetManager のデータ順序に反映
        new_order = []
        for i in range(self.list_widget.count()):
            new_order.append(self.list_widget.item(i).data(Qt.UserRole))
        self.asset_mgr._order_ids = new_order

    def on_item_double_clicked(self, item):
        self.assetSelected.emit(item.data(Qt.UserRole))

    def show_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        asset_id = item.data(Qt.UserRole)

        menu = QMenu()
        if not self.show_hidden:
            hide_act = menu.addAction("棚から隠す")
            hide_act.triggered.connect(
                lambda: self.asset_mgr.toggle_visibility(asset_id)
            )
        else:
            show_act = menu.addAction("棚に戻す")
            show_act.triggered.connect(
                lambda: self.asset_mgr.toggle_visibility(asset_id)
            )

        remove_act = menu.addAction("完全に削除する")
        remove_act.triggered.connect(lambda: self.asset_mgr.unregister_asset(asset_id))

        menu.exec(self.list_widget.mapToGlobal(pos))
