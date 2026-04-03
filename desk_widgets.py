from PySide6.QtWidgets import (
    QPushButton,
    QFileDialog,
    QMessageBox,
    QStackedWidget,
    QListWidget,
    QListWidgetItem,
    QListView,
    QAbstractItemView,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
    QMenu,
    QInputDialog,
)
from PySide6.QtCore import Qt, Signal, QSize, QThread, QTimer
import os
from workspace_models import (
    SourceAsset,
    CroppedAsset,
    JoinedAsset,
    WorkspaceAsset,
)
from pdf_processor import PdfProcessor
from preview_view import PdfPreviewView
from graphics_view import PdfGraphicsView
from worker import JoinPreviewWorker, OrganizePreviewWorker


class BaseDeskWidget(QStackedWidget):
    """
    すべての作業デスク（タブ）の基底クラス。
    「編集画面」と「プレビュー画面」をパタッと裏返して切り替える機能を共通化。
    """

    fileDropped = Signal(str)
    selectionChanged = Signal(object)
    contentChanged = Signal(list)

    supports_template = False
    """このデスクがテンプレート機能（切り抜き枠の自動配置など）をサポートしているか"""

    sync_title_with_asset = False
    """アセットを読み込んだ際にタブの名前をアセット名（ファイル名）に同期させるか"""

    def can_accept_asset(self, asset: WorkspaceAsset) -> bool:
        """このデスクが指定されたアセットを読み込めるか判定（デフォルトはすべて受け入れる）"""
        return True

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = None  # 子クラスで初期化
        self.preview = PdfPreviewView()

    def finalize_init(self, editor_widget):
        """子クラスでの初期化後にウィジェットを登録する"""
        if editor_widget:
            self.addWidget(editor_widget)
        self.addWidget(self.preview)

    def set_mode(self, preview_mode: bool):
        """表示モードを切り替える（共通ロジック）"""
        if preview_mode:
            self.setCurrentWidget(self.preview)
            self.on_preview_enter()
        else:
            self.preview.stop_rendering()
            self.setCurrentWidget(self.editor_widget)

    def on_preview_enter(self):
        """プレビュー開始時のロジック。各子クラスでオーバーライドする"""
        pass

    def set_asset(self, asset: WorkspaceAsset):
        """アセットをこのデスクに読み込む。挙動はデスクの種類による"""
        pass

    def is_preview_mode(self):
        return self.currentWidget() == self.preview

    def is_ready_to_load(self) -> bool:
        """このデスクに新しいアセットをロードしてもよいか判定する（必要に応じてオーバーライドする）"""
        return True


class CropDeskWidget(BaseDeskWidget):
    """
    1つのタブ内で「切り抜き編集画面」と「プレビュー画面」を管理するデスクウィジェット。
    """

    supports_template = True
    sync_title_with_asset = True

    def can_accept_asset(self, asset: WorkspaceAsset) -> bool:
        """CropDesk は 連結プロジェクト（JoinedAsset）を直接開くことはできない"""
        return not isinstance(asset, JoinedAsset)

    def __init__(self, asset_mgr, parent=None):
        super().__init__(parent)
        self.asset_mgr = asset_mgr
        self.parent_asset_id = None  # 現在読み込んでいる素材のID

        # エディタ部（PDF表示部 + 操作バー）
        self.editor_widget = QWidget()
        layout = QVBoxLayout(self.editor_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # 操作バー
        ctrl_bar = QHBoxLayout()
        self.save_btn = QPushButton("素材棚に登録")
        self.save_btn.setStyleSheet(
            "font-weight: bold; background-color: #fce4ec; height: 35px;"
        )
        self.save_btn.clicked.connect(self.save_as_asset)
        ctrl_bar.addWidget(self.save_btn)

        self.export_btn = QPushButton("PDFとして保存")
        self.export_btn.setStyleSheet(
            "font-weight: bold; background-color: #e8f5e9; height: 35px;"
        )
        self.export_btn.clicked.connect(self.export_as_pdf)
        ctrl_bar.addWidget(self.export_btn)

        layout.addLayout(ctrl_bar)

        self.editor = PdfGraphicsView()
        self.editor.fileDropped.connect(self.fileDropped.emit)
        self.editor.selectionChanged.connect(self.selectionChanged.emit)
        self.editor.rectsChanged.connect(self.contentChanged.emit)
        layout.addWidget(self.editor)

        self.finalize_init(self.editor_widget)

    def save_as_asset(self):
        """現在の切り抜き設定を CroppedAsset として素材棚に登録する"""
        if not self.parent_asset_id:
            QMessageBox.warning(self, "エラー", "素材が読み込まれていません")
            return

        rects = self.editor.rects
        if not rects:
            QMessageBox.warning(self, "エラー", "切り抜き枠が設定されていません")
            return

        name, ok = QInputDialog.getText(
            self, "パーツとして保存", "素材名:", text="New_Part"
        )
        if not ok or not name:
            return

        # myCropBox (UIオブジェクト) のリストから実際のシーン座標 (QRectF) を抽出する
        scene_rects = [
            box.mapToScene(box.rect()).boundingRect() for box in self.editor.rects
        ]

        # 素材棚に登録
        self.asset_mgr.create_cropped(
            self.parent_asset_id, scene_rects, self.editor.scale_factor, name=name
        )
        QMessageBox.information(
            self, "完了", f"パーツ '{name}' を素材棚に登録しました。"
        )

    def export_as_pdf(self):
        """現在の切り抜き枠を物理PDFファイルとして出力保存する"""
        if not self.editor.pdf_path:
            QMessageBox.warning(self, "エラー", "PDFファイルが読み込まれていません")
            return

        if not self.editor.rects:
            QMessageBox.warning(self, "エラー", "切り抜き枠が設定されていません")
            return

        # 1. 保存先の決定
        base, ext = os.path.splitext(os.path.basename(self.editor.pdf_path))
        default_name = f"{base}_cropped{ext}"
        output_path, _ = QFileDialog.getSaveFileName(
            self, "PDFとして保存", default_name, "PDF Files (*.pdf)"
        )
        if not output_path:
            return

        # 2. 実行
        try:
            # UIオブジェクトから座標リストを取得 (graphics_view に集約されている)
            crop_rects = self.editor.get_crop_coordinates()

            PdfProcessor.crop_and_save(
                input_path=self.editor.pdf_path,
                output_path=output_path,
                crop_rects=crop_rects,
                scale_factor=self.editor.scale_factor,
            )
            QMessageBox.information(self, "完了", f"PDFを保存しました：\n{output_path}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存に失敗しました：\n{str(e)}")

    def on_preview_enter(self):
        """切り抜き枠の状態からプレビューを生成"""
        self.preview.update_previews(
            self.editor.pdf_path, self.editor.rects, self.editor.scale_factor
        )

    def set_asset(self, asset: WorkspaceAsset):
        """アセットの種類を判別して、キャンバスの初期化と復元を行う"""
        match asset:
            case SourceAsset():
                self.parent_asset_id = asset.id
                self.editor.load_from_path(asset.path)

            case CroppedAsset():
                parent = self.asset_mgr.get_asset(asset.parent_id)
                if not parent:
                    QMessageBox.warning(
                        self, "エラー", "親となる素材が見つからないため復元できません。"
                    )
                    return
                # 親としてロード
                self.parent_asset_id = parent.id
                self.editor.load_from_path(parent.path)
                # 枠を復元
                self.editor.restore_boxes(asset.crop_rects)

    def is_ready_to_load(self) -> bool:
        """このデスクに新しいアセットをロードしてもよいか判定する"""
        return self.editor.ask_discard_changes()


class JoinListWidget(QListWidget):
    """ファイルドロップを受け付けるカスタム連結リストウィジェット"""

    fileDropped = Signal(str)
    orderChanged = Signal()  # 並び替えや削除が行われたときに発火

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QListWidget.InternalMove)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        self.setStyleSheet("""
            QListWidget { font-size: 14px; padding: 10px; border: 1px solid #ccc; border-radius: 4px; }
            QListWidget::item { height: 45px; border-bottom: 1px solid #eee; }
            QListWidget::item:selected { background-color: #e3f2fd; color: #0d47a1; }
        """)

        # モデルの変更を検知して orderChanged を発火させる
        self.model().rowsMoved.connect(lambda: self.orderChanged.emit())
        self.model().rowsInserted.connect(lambda: self.orderChanged.emit())
        self.model().rowsRemoved.connect(lambda: self.orderChanged.emit())

    def get_item_ids(self):
        """現在のリストの並び順に基づいてアセットIDのリストを返す"""
        ids = []
        for i in range(self.count()):
            item = self.item(i)
            asset_id = item.data(Qt.UserRole)
            if asset_id:
                ids.append(asset_id)
        return ids

    def keyPressEvent(self, event):
        """Delete / Backspace キーで選択中アイテムを削除"""
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.remove_selected_items()
        else:
            super().keyPressEvent(event)

    def remove_selected_items(self):
        """選択されているアイテムをリストから削除"""
        for item in self.selectedItems():
            self.takeItem(self.row(item))
        self.orderChanged.emit()

    def _show_context_menu(self, pos):
        """右クリックメニューを表示"""
        menu = QMenu(self)
        remove_action = menu.addAction("⚠️ 選択したアイテムを削除")
        remove_action.triggered.connect(self.remove_selected_items)

        menu.addSeparator()
        clear_action = menu.addAction("🗑️ リストを空にする")
        clear_action.triggered.connect(lambda: (self.clear(), self.orderChanged.emit()))

        menu.exec(self.mapToGlobal(pos))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        # 外部ファイルがドロップされた場合のみ処理
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                if file_path.lower().endswith(
                    (".pdf", ".png", ".jpg", ".jpeg", ".bmp")
                ):
                    self.fileDropped.emit(file_path)
            event.acceptProposedAction()
        else:
            # 内部の並び替えドロップなどは親クラス（QListWidget）に任せる
            super().dropEvent(event)


class JoinDeskWidget(BaseDeskWidget):
    """
    1つのタブ内で「ファイル連結順序リスト」と「プレビュー画面」を管理するデスクウィジェット。
    """

    def __init__(self, asset_mgr, parent=None):
        super().__init__(parent)
        self.asset_mgr = asset_mgr

        # エディタ部（カスタム連結リスト + 操作バー）
        self.editor_widget = QWidget()
        layout = QVBoxLayout(self.editor_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # 保存バー
        ctrl_bar = QHBoxLayout()

        self.save_btn = QPushButton("素材棚に登録")
        self.save_btn.setStyleSheet(
            "font-weight: bold; background-color: #e3f2fd; height: 35px;"
        )
        self.save_btn.clicked.connect(self.save_as_asset)
        ctrl_bar.addWidget(self.save_btn)

        self.export_btn = QPushButton("PDFとして保存")
        self.export_btn.setStyleSheet(
            "font-weight: bold; background-color: #e8f5e9; height: 35px;"
        )
        self.export_btn.clicked.connect(self.export_as_pdf)
        ctrl_bar.addWidget(self.export_btn)

        layout.addLayout(ctrl_bar)

        self.editor = JoinListWidget()
        layout.addWidget(self.editor)

        self.finalize_init(self.editor_widget)

    def save_as_asset(self):
        """現在のリストを JoinedAsset として素材棚に登録する"""
        if self.editor.count() == 0:
            QMessageBox.warning(self, "エラー", "連結するアイテムがありません")
            return
        elif self.editor.count() == 1:
            QMessageBox.warning(self, "エラー", "連結するアイテムが1つしかありません")
            return

        name, ok = QInputDialog.getText(
            self, "素材として登録", "プロジェクト名:", text="New_Project"
        )
        if not ok or not name:
            return

        item_ids = self.editor.get_item_ids()

        # モデルに登録
        self.asset_mgr.create_joined(item_ids, name=name)
        QMessageBox.information(
            self, "完了", f"アセット '{name}' を素材棚に登録しました。"
        )

    def export_as_pdf(self):
        """現在のリストを物理PDFファイルとして出力保存する"""
        item_ids = self.editor.get_item_ids()
        if not item_ids:
            QMessageBox.warning(self, "エラー", "保存するアイテムがありません")
            return

        # 1. 保存先の決定
        file_path, _ = QFileDialog.getSaveFileName(
            self, "PDFとして保存", "joined_output.pdf", "PDF Files (*.pdf)"
        )
        if not file_path:
            return

        # 2. メタデータの収集
        assets_metadata = []
        for asset_id in item_ids:
            asset = self.asset_mgr.get_asset(asset_id)
            if not asset:
                continue

            match asset:
                case SourceAsset():
                    assets_metadata.append(
                        {"path": asset.path, "crop_coords": [], "scale_factor": 1.0}
                    )
                case CroppedAsset():
                    parent = self.asset_mgr.get_asset(asset.parent_id)
                    if parent and isinstance(parent, SourceAsset):
                        coords = [
                            (r.left(), r.top(), r.right(), r.bottom())
                            for r in asset.crop_rects
                        ]
                        assets_metadata.append(
                            {
                                "path": parent.path,
                                "crop_coords": coords,
                                "scale_factor": asset.scale_factor,
                            }
                        )

        # 3. 物理書き出し実行
        try:
            PdfProcessor.join_and_save(file_path, assets_metadata)
            QMessageBox.information(self, "完了", f"PDFを保存しました：\n{file_path}")
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"保存に失敗しました：\n{str(e)}")

    def on_preview_enter(self):
        """連結リストの各アセット（Source/Cropped）から画像を収集して非同期でプレビュー表示"""
        item_ids = self.editor.get_item_ids()
        if not item_ids:
            self.preview.clear_display()
            return

        assets_metadata = []

        # リストのアイテムを上から順に走査し、レンダリングに必要なメタデータを収集
        for asset_id in item_ids:
            asset = self.asset_mgr.get_asset(asset_id)
            if not asset:
                continue

            match asset:
                case SourceAsset():
                    assets_metadata.append(
                        {"path": asset.path, "crop_coords": [], "scale_factor": 1.0}
                    )
                case CroppedAsset():
                    # 親（Source）を取得してパスを特定
                    parent = self.asset_mgr.get_asset(asset.parent_id)
                    if parent and isinstance(parent, SourceAsset):
                        # QRectF のリストを (l,t,r,b) のタプルリストに変換
                        coords = [
                            (r.left(), r.top(), r.right(), r.bottom())
                            for r in asset.crop_rects
                        ]
                        assets_metadata.append(
                            {
                                "path": parent.path,
                                "crop_coords": coords,
                                "scale_factor": asset.scale_factor,
                            }
                        )

        # 汎用化された PdfPreviewView の非同期レンダリングを呼び出す
        self.preview.update_joined_previews(assets_metadata)

    def set_asset(self, asset: WorkspaceAsset):
        """結合リストにアイテムを追加する"""
        match asset:
            case SourceAsset():
                icon = "📄"
            case JoinedAsset():
                icon = "🔗"
            case _:
                icon = "✂️"  # CroppedAsset 等

        item = QListWidgetItem(f"{icon} {asset.name}")
        item.setData(Qt.UserRole, asset.id)
        self.editor.addItem(item)


class OrganizeListWidget(QListWidget):
    """
    OrganizeDeskのサムネイル一覧表示用リストウィジェット。
    画像のドラッグ＆ドロップによる並べ替え（InternalMove）と、外部からの挿入ドロップを受け付ける。
    """

    items_added = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListView.ListMode)  # グリッド表示
        self.setDropIndicatorShown(True)
        self.setMovement(QListView.Snap)  # 自由配置を禁止し、リストのフローに従わせる
        self.setGridSize(QSize(150, 200))
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)  # ウィンドウ幅に合わせて折り返し
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)  # 複数選択可
        self.setDragEnabled(True)  # ドラッグ開始を明示的に有効化
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setAcceptDrops(True)
        self.setIconSize(QSize(100, 140))  # 仮のサイズ設定
        self.setSpacing(10)

    def dragEnterEvent(self, event):
        """外部からのファイル（画像）ドラッグ、または内部移動を判別して許可する"""
        if event.mimeData().hasUrls():
            # 外部ファイルパスが含まれている場合、画像ファイルが1つでもあれば許可
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                ext = os.path.splitext(file_path)[1].lower()
                if ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
                    event.acceptProposedAction()
                    return
        # それ以外（内部移動など）は親クラスの標準処理に任せる
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        """ドラッグ中、常にドロップ可能か判定し続ける"""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                ext = os.path.splitext(file_path)[1].lower()
                if ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
                    event.acceptProposedAction()
                    return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        """内部移動、または外部画像の挿入を処理する"""
        if event.mimeData().hasUrls():
            # 外部からのファイルドロップの場合
            drop_pos = event.position().toPoint()
            target_item = self.itemAt(drop_pos)
            if target_item:
                target_row = self.row(target_item)
            else:
                target_row = self.count()

            # 画像ファイルを抽出してアイテムを追加
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()
                ext = os.path.splitext(file_path)[1].lower()
                if ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif"):
                    item = QListWidgetItem(f"🖼️ {os.path.basename(file_path)}")
                    # 画像用のメタ情報を保持
                    metadata = {
                        "type": "image_file",
                        "source_path": file_path,
                        "page_index": None,
                    }
                    item.setData(Qt.UserRole, metadata)
                    # マウスが離された位置（または末尾）に挿入
                    self.insertItem(target_row, item)
                    target_row += 1  # 複数ドロップ時に順番を維持

            event.acceptProposedAction()
            self.items_added.emit()
        else:
            # 内部の並べ替え（InternalMove）は標準処理に任せる
            super().dropEvent(event)


class OrganizeDeskWidget(BaseDeskWidget):
    """
    ベースPDFと画像をサムネイル展開して並べ替え・削除・挿入を行うデスク。
    """

    def __init__(self, asset_mgr, parent=None):
        super().__init__(parent)
        self.asset_mgr = asset_mgr

        # UI構築
        toolbar = QHBoxLayout()
        test_btn = QPushButton("テストアイテム追加")
        test_btn.clicked.connect(self._add_test_data)
        toolbar.addWidget(test_btn)
        toolbar.addStretch()

        self.editor = OrganizeListWidget()
        self.editor.items_added.connect(self.request_previews)

        self.worker_thread = None
        self.worker = None

        # BaseDeskWidgetの構造に合わせた下部プレビュー枠（不要かもしれないが形式上残す）
        self.preview = PdfPreviewView()

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar)
        layout.addWidget(self.editor)

        self.addWidget(container)  # 編集画面
        self.addWidget(self.preview)  # プレビュー画面

    def _add_test_data(self):
        """Step 1 確認用の仮データ追加機能"""
        count = self.editor.count()
        item = QListWidgetItem(f"仮アイテム {count + 1}")
        self.editor.addItem(item)
        self.request_previews()

    def set_asset(self, asset: WorkspaceAsset):
        """
        [Step 2-1実装] アセットを読み込んだ時の処理。
        ベースPDFの全ページを仮アイテムとして展開する。
        """
        if not hasattr(asset, "path") or not os.path.exists(asset.path):
            return

        # 既存アイテムをクリア
        self.editor.clear()

        # PDFを開いてページ数を取得
        import fitz

        try:
            with fitz.open(asset.path) as doc:
                page_count = len(doc)
        except Exception as e:
            QMessageBox.critical(self, "エラー", f"PDFの読み込みに失敗しました: {e}")
            return

        # 各ページをリストアイテムとして展開
        for i in range(page_count):
            item = QListWidgetItem(f"📄 Page {i + 1}")
            # メタ情報を保持（Step 5の書き出しで使用）
            metadata = {"type": "pdf_page", "source_path": asset.path, "page_index": i}
            item.setData(Qt.UserRole, metadata)
            self.editor.addItem(item)

        # 全件追加後にワーカーを起動
        QTimer.singleShot(100, self.request_previews)

    def request_previews(self):
        """
        [Step 3-2 / 3-3実装] アイコンが未生成のアイテムを探し、ワーカーに依頼する。
        """
        requests = []
        for i in range(self.editor.count()):
            item = self.editor.item(i)
            if item.icon().isNull():
                meta = item.data(Qt.UserRole)
                if meta:
                    requests.append(meta)

        if not requests:
            return

        # 前のワーカーがあればキャンセル
        if self.worker and self.worker_thread:
            self.worker.cancel()
            self.worker_thread.quit()
            self.worker_thread.wait()

        self.worker_thread = QThread()
        self.worker = OrganizePreviewWorker(requests)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        # Step 3-3 用：ワーカーから画像が届いたらアイコンをセット
        self.worker.page_ready.connect(self.apply_previews)

        self.worker_thread.start()

    def apply_previews(self, batch: list):
        """
        [Step 3-3実装] ワーカーから届いたバッチ（メタデータと画像のペア）を、
        現在のリストアイテム内のメタ情報と照合してアイコンをセットする。
        """
        from PySide6.QtGui import QIcon, QPixmap

        for meta, img in batch:
            pixmap = QPixmap.fromImage(img)
            icon = QIcon(pixmap)

            # 現在のリストの中から、メタデータが一致するアイテムを探して適用する
            for i in range(self.editor.count()):
                item = self.editor.item(i)
                item_meta = item.data(Qt.UserRole)
                if item_meta == meta:
                    item.setIcon(icon)
                    # 最初の1回だけ、見栄えのためにテキストを消す（任意）
                    if "Page" in item.text() or "🖼️" in item.text():
                        item.setText("")
                    break  # 同じアイテムは1つだけのはずなので抜ける

    def can_accept_asset(self, asset: WorkspaceAsset) -> bool:
        # OrganizeDesk はどのAssetでも一旦受け入れ可能とする（現状）
        return True


# アセット型とデフォルトで開くべきデスク型のリレーション定義
DEFAULT_DESK_MAP: dict[type[WorkspaceAsset], type[BaseDeskWidget]] = {
    JoinedAsset: JoinDeskWidget,
    SourceAsset: CropDeskWidget,
    CroppedAsset: CropDeskWidget,
}
