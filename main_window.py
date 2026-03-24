import os
from typing import Optional, List, Type
from PySide6.QtWidgets import (
    QMainWindow,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QTabWidget,
    QDockWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QDragEnterEvent, QDragMoveEvent, QDropEvent
from workspace_models import (
    AssetManager,
    JoinedAsset,
    WorkspaceAsset,
)
from myDockContent import PreviewPanel, PropertyPanel, AssetShelfWidget
from pdf_processor import PdfProcessor
from desk_widgets import BaseDeskWidget, CropDeskWidget, JoinDeskWidget
from graphics_view import PdfGraphicsView


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDFCropper2")
        self.resize(1200, 850)
        self.setAcceptDrops(True)  # ドラッグ＆ドロップを許可

        # 素材管理マネージャー
        self.asset_mgr = AssetManager()

        # カスタムメニューバーを使用
        # self.setMenuBar(HoverMenuBar(self))
        menu_bar = self.menuBar()

        # ファイルメニュー
        file_menu = menu_bar.addMenu("ファイル")

        open_action = file_menu.addAction("PDFを開く")
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_file)

        add_tab_action = file_menu.addAction("切り抜きタブを追加")
        add_tab_action.setShortcut("Ctrl+T")
        add_tab_action.triggered.connect(
            lambda _=False: self.add_new_tab(CropDeskWidget)
        )

        add_join_tab_action = file_menu.addAction("結合タブを追加")
        add_join_tab_action.setShortcut("Ctrl+J")
        add_join_tab_action.triggered.connect(
            lambda _=False: self.add_new_tab(JoinDeskWidget)
        )

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

        undo_action = edit_menu.addAction("元に戻す")
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(
            lambda: self.current_view().undo() if self.current_view() else None
        )

        redo_action = edit_menu.addAction("やり直し")
        redo_action.setShortcuts(["Ctrl+Shift+Z", "Ctrl+Y"])
        redo_action.triggered.connect(
            lambda: self.current_view().redo() if self.current_view() else None
        )

        edit_menu.addSeparator()

        clear_action = edit_menu.addAction("選択範囲をクリア")
        clear_action.setShortcut("Ctrl+Shift+X")
        clear_action.triggered.connect(
            lambda: (
                self.current_view().clear_selections() if self.current_view() else None
            )
        )

        # ワークスペース操作ツールバー
        self.workspace_toolbar = self.addToolBar("ワークスペース")
        self.workspace_toolbar.setMovable(False)

        self.action_new_crop = QAction("✂️ クロップ", self)
        self.action_new_crop.setToolTip("新しい切り抜きタブを作成")
        self.action_new_crop.triggered.connect(
            lambda _=False: self.add_new_tab(CropDeskWidget)
        )

        self.action_new_join = QAction("🔗 ジョイン", self)
        self.action_new_join.setToolTip("新しい結合タブを作成")
        self.action_new_join.triggered.connect(
            lambda _=False: self.add_new_tab(JoinDeskWidget)
        )

        self.workspace_toolbar.addAction(self.action_new_crop)
        self.workspace_toolbar.addAction(self.action_new_join)
        self.workspace_toolbar.addSeparator()

        # 表示モード切替ツールバー
        self.mode_toolbar = self.addToolBar("表示モード")
        self.mode_toolbar.setMovable(False)

        self.action_editor = QAction("編集モード", self)
        self.action_editor.setCheckable(True)
        self.action_editor.setChecked(True)
        self.action_editor.triggered.connect(lambda: self._handle_mode_change(False))

        self.action_preview = QAction("プレビューモード", self)
        self.action_preview.setCheckable(True)
        self.action_preview.triggered.connect(lambda: self._handle_mode_change(True))

        self.mode_toolbar.addAction(self.action_editor)
        self.mode_toolbar.addAction(self.action_preview)

        self.tab_widget = QTabWidget()
        self.tab_widget.setTabsClosable(True)
        self.tab_widget.tabCloseRequested.connect(self.remove_tab)
        # タブ切り替え時にタイトルとプロパティの接続を更新
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tab_widget)

        # 素材棚サイドバーを構築
        self.shelf_dock = QDockWidget("素材棚", self)
        self.shelf_dock.setAllowedAreas(Qt.LeftDockWidgetArea)
        self.shelf_widget = AssetShelfWidget(self.asset_mgr)
        self.shelf_dock.setWidget(self.shelf_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.shelf_dock)

        # 棚のアイテムがダブルクリックされたときの処理
        self.shelf_widget.assetSelected.connect(self.on_asset_from_shelf)

        # ドックウィジェット
        # ドックウィジェットのタブ位置を上部に設定
        self.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)
        # プロパティパネル
        self.dock = QDockWidget("プロパティ", self)
        self.dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.prop_panel = PropertyPanel()
        self.prop_panel.orderChanged.connect(self._handle_reorder)
        self.prop_panel.syncSizeChanged.connect(self._handle_sync_size_changed)
        self.prop_panel.syncSymmetryChanged.connect(self._handle_sync_symmetry_changed)
        self.dock.setWidget(self.prop_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock)

        # 表示メニュー
        view_menu = menu_bar.addMenu("表示")
        view_menu.addAction(self.dock.toggleViewAction())

        # プレビュー用のドックを追加
        self.preview_dock = QDockWidget("切り抜きプレビュー", self)
        self.preview_panel = PreviewPanel()
        self.preview_dock.setWidget(self.preview_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.preview_dock)

        view_menu.addAction(self.preview_dock.toggleViewAction())

        # ドックの初期サイズ設定
        self.resizeDocks([self.dock, self.preview_dock], [300, 300], Qt.Vertical)

        # 最初のタブを追加
        self.add_new_tab()

        # テンプレート用ツールバー
        self.template_toolbar = self.addToolBar("テンプレート")

        btn_2v = QPushButton("2分割(左右)")
        btn_2v.clicked.connect(self._apply_template_2v)
        self.template_toolbar.addWidget(btn_2v)

        btn_2h = QPushButton("2分割(上下)")
        btn_2h.clicked.connect(self._apply_template_2h)
        self.template_toolbar.addWidget(btn_2h)

        btn_4 = QPushButton("4分割")
        btn_4.clicked.connect(self._apply_template_4)
        self.template_toolbar.addWidget(btn_4)

        self.template_toolbar.addSeparator()

        btn_auto = QPushButton("✨ 枠線を自動認識")
        btn_auto.setStyleSheet("font-weight: bold; color: #005a9e;")
        btn_auto.clicked.connect(self._handle_auto_detect)
        self.template_toolbar.addWidget(btn_auto)

    def _apply_template_2v(self) -> None:
        view = self.current_view()
        if view:
            view.add_template_2v()

    def _apply_template_2h(self) -> None:
        view = self.current_view()
        if view:
            view.add_template_2h()

    def _apply_template_4(self) -> None:
        view = self.current_view()
        if view:
            view.add_template_4()

    def _handle_auto_detect(self) -> None:
        view = self.current_view()
        if view:
            view.auto_detect_frames()

    def _on_tab_changed(self, index: int) -> None:
        """タブが切り替わったら、現在のビューの選択状態をパネルに繋ぎ変える"""
        self.update_window_title()
        container = self.current_desk()
        if not container:
            return

        # ツールバーのボタン状態をタブに合わせる
        is_preview = container.is_preview_mode()
        self.action_editor.setChecked(not is_preview)
        self.action_preview.setChecked(is_preview)

        view = self.current_view()
        if view:
            # 初期状態を反映
            self.prop_panel.update_list(view.rects)
            self.prop_panel.update_sync_settings(view.sync_size, view.sync_symmetry)
            self.preview_panel.update_previews(view)
            view._on_scene_selection_changed()
        else:
            self.prop_panel.set_target(None)
            self.prop_panel.update_list([])
            self.preview_panel.update_previews(None)

    def _handle_mode_change(self, preview_mode: bool) -> None:
        """ツールバーでのモード切替を処理"""
        desk = self.current_desk()
        if desk and isinstance(desk, BaseDeskWidget):
            desk.set_mode(preview_mode)
            self.action_editor.setChecked(not preview_mode)
            self.action_preview.setChecked(preview_mode)

    def _handle_selection_changed(self, item: object) -> None:
        """信号の送信元が現在のタブの場合のみパネルを更新する"""
        if self.sender() == self.current_view():
            self.prop_panel.set_target(item)

    def _handle_rects_changed(self, rects: List[object]) -> None:
        """信号の送信元が現在のタブの場合のみパネルを更新する"""
        view = self.current_view()
        if self.sender() == view:
            self.prop_panel.update_list(rects)
            self.preview_panel.update_previews(view)

    def _handle_reorder(self, new_order: List[object]) -> None:
        """ドックでの並び替えを現在のビューに反映する"""
        view = self.current_view()
        if view:
            view.reorder_rects(new_order)
            self.preview_panel.update_previews(view)

    def _handle_sync_size_changed(self, enabled: bool) -> None:
        view = self.current_view()
        if view:
            view.sync_size = enabled

    def _handle_sync_symmetry_changed(self, enabled: bool) -> None:
        view = self.current_view()
        if view:
            view.sync_symmetry = enabled

    def current_desk(self) -> Optional[BaseDeskWidget]:
        """現在のアクティブなタブに含まれるデスクウィジェットを返す"""
        return self.tab_widget.currentWidget()

    def current_view(self) -> Optional[PdfGraphicsView]:
        desk = self.current_desk()
        if isinstance(desk, CropDeskWidget):
            return desk.editor
        return None

    def add_new_tab(
        self, desk_class: Type[BaseDeskWidget] = CropDeskWidget
    ) -> BaseDeskWidget:
        """新しいタブを追加する。空いている最小の番号を割り振る"""
        prefix = "Crop" if desk_class == CropDeskWidget else "Join"

        # 現在使用されている番号をすべて取得
        used_numbers = set()
        for i in range(self.tab_widget.count()):
            text = self.tab_widget.tabText(i)
            if text.startswith(f"{prefix} "):
                try:
                    num = int(text.split(" ")[1])
                    used_numbers.add(num)
                except (IndexError, ValueError):
                    pass

        # 1から順に確認して空いている最小の番号を探す
        new_num = 1
        while new_num in used_numbers:
            new_num += 1

        # クラスによってプレフィックスと引数を変える
        if desk_class == JoinDeskWidget:
            prefix_label = "🔗 Join"
            new_desk = JoinDeskWidget(self.asset_mgr)
        else:
            prefix_label = "✂️ Crop"
            new_desk = CropDeskWidget(self.asset_mgr)

        # クロップデスク固有の初期接続
        if isinstance(new_desk, CropDeskWidget):
            new_view = new_desk.editor
            new_view.fileDropped.connect(self.load_new_pdf)
            new_view.selectionChanged.connect(self._handle_selection_changed)
            new_view.rectsChanged.connect(self._handle_rects_changed)
            new_desk.requestRouting.connect(self._handle_routing_request)
        elif isinstance(new_desk, JoinDeskWidget):
            # ジョインタブ固有のドロップ信号を接続
            new_desk.editor.fileDropped.connect(self.load_new_pdf)

        index = self.tab_widget.addTab(new_desk, f"{prefix_label} {new_num}")
        self.tab_widget.setCurrentIndex(index)
        self.update_window_title()

        # ツールバーの状態を更新
        self._on_tab_changed(index)

        return new_desk

    def update_window_title(self) -> None:
        """現在のタブの名前に基づいてウィンドウタイトルを更新する"""
        index = self.tab_widget.currentIndex()
        if index != -1:
            tab_text = self.tab_widget.tabText(index)
            self.setWindowTitle(f"PDFCropper2 - {tab_text}")
        else:
            self.setWindowTitle("PDFCropper2")

    def close_current_tab(self) -> None:
        """現在のタブを閉じる"""
        current_index = self.tab_widget.currentIndex()
        if current_index != -1:
            self.remove_tab(current_index)

    def _handle_routing_request(self, asset: WorkspaceAsset) -> None:
        """CropDeskWidgetから送信された、別タブでのロード要求を処理する"""
        if isinstance(asset, JoinedAsset):
            # 新しいジョインタブを開いて、そこにアセットをロードする
            new_desk = self.add_new_tab(JoinDeskWidget)
            new_desk.set_asset(asset)

    def remove_tab(self, index: int) -> None:
        """指定したインデックスのタブを閉じる"""
        self.tab_widget.removeTab(index)

        # 全てのタブが閉じられたら新しい空のタブを作る
        if self.tab_widget.count() == 0:
            self.add_new_tab()

    def open_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self, "素材を追加", "", "PDF/Image Files (*.pdf *.png *.jpg *.jpeg *.bmp)"
        )
        if file_path:
            # マネージャーを通じて棚へ追加
            self.asset_mgr.create_source(file_path)

    def on_asset_from_shelf(self, asset_id: str) -> None:
        asset = self.asset_mgr.get_asset(asset_id)
        if not asset:
            print(f"Asset {asset_id} not found")
            return

        # 現在のデスク（タブ）を取得
        desk = self.current_desk()
        if not desk:
            # タブが全くない場合は、アセットに適したタブを新規作成する
            if isinstance(asset, JoinedAsset):
                desk = self.add_new_tab(JoinDeskWidget)
            else:
                desk = self.add_new_tab(CropDeskWidget)

        # 許可を求めてからロード（切り抜きデスクの場合のみ）
        if isinstance(desk, CropDeskWidget):
            if not desk.editor.ask_discard_changes():
                return

        # ロード実行
        desk.set_asset(asset)

        # 切り抜きデスクの場合はタブ名をファイル名に同期
        if isinstance(desk, CropDeskWidget):
            current_index = self.tab_widget.currentIndex()
            self.tab_widget.setTabText(current_index, asset.name)
            self.update_window_title()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            # 渡されたURL（ファイルパス）が対象ファイルかチェック
            for url in event.mimeData().urls():
                if (
                    url.toLocalFile()
                    .lower()
                    .endswith((".pdf", ".png", ".jpg", ".jpeg", ".bmp"))
                ):
                    event.acceptProposedAction()
                    return

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if (
                    url.toLocalFile()
                    .lower()
                    .endswith((".pdf", ".png", ".jpg", ".jpeg", ".bmp"))
                ):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".bmp")):
                self.load_new_pdf(file_path)
                break

    def load_new_pdf(self, file_path: str) -> None:
        """指定されたまたは現在のビューに、素材棚を経由してPDFをロードする"""
        # 1. 何はともあれ素材棚（AssetManager）に登録し、アイコンが並ぶようにする
        asset = self.asset_mgr.create_source(file_path)

        # 2. ロード対象のデスクを特定
        desk = self.current_desk()
        if not desk:
            # タブがない場合は自動的にクロップタブを作成
            desk = self.add_new_tab(CropDeskWidget)

        # 3. デスクの種類に関わらずアセットを流し込む（set_asset 側で処理を分岐）
        if isinstance(desk, CropDeskWidget):
            # キャンバスへの読み込み時は、破棄確認を行う
            if not desk.editor.ask_discard_changes():
                return
            desk.set_asset(asset)
            # クロップタブのみ、タブ名とタイトルをファイル名に同期
            idx = self.tab_widget.indexOf(desk)
            self.tab_widget.setTabText(idx, asset.name)
            self.update_window_title()
        else:
            # 他のデスク（Join等）なら単純に追加
            desk.set_asset(asset)

    def process_crop(self) -> None:
        view = self.current_view()
        if not view:
            return
        target_pdf = view.pdf_path

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
        output_path, _ = QFileDialog.getSaveFileName(
            self, "保存", default_name, "PDF Files (*.pdf)"
        )
        if not output_path:
            print("QFileDialog.getSaveFileName() returned empty path")
            return

        try:
            # 1. UIの部品(myCropBox)から、純粋な座標データ(タプル)だけを抽出する
            crop_coordinates = []
            for item in view.rects:
                s_rect = item.mapToScene(item.rect()).boundingRect()
                crop_coordinates.append(
                    (s_rect.left(), s_rect.top(), s_rect.right(), s_rect.bottom())
                )

            # 2. PDF処理の専門家にデータを丸投げする
            PdfProcessor.crop_and_save(
                input_path=target_pdf,
                output_path=output_path,
                crop_rects=crop_coordinates,
                scale_factor=view.scale_factor,
            )

            QMessageBox.information(self, "完了", "保存しました")
        except Exception as e:
            QMessageBox.critical(self, "エラー", str(e))
