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
    WorkspaceAsset,
)
from dock_panels import PreviewPanel, PropertyPanel, AssetShelfWidget
from workspace_tabs import WorkspaceTabWidget
from desk_widgets import (
    BaseDeskWidget,
    CropDeskWidget,
    JoinDeskWidget,
    DEFAULT_DESK_MAP,
)
from graphics_view import PdfGraphicsView


class MainWindow(QMainWindow):
    SUPPORTED_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".bmp")

    def __init__(self) -> None:
        super().__init__()
        self._init_settings()
        self._init_menu_bar()
        self._init_toolbars()
        self._init_central_widget()
        self._init_docks()

        # 最初のタブを追加
        self.add_new_tab()

    def _init_settings(self) -> None:
        self.setWindowTitle("PDFCropper2")
        self.resize(1200, 850)
        self.setAcceptDrops(True)  # ドラッグ＆ドロップを許可
        self.asset_mgr = AssetManager()

    def _init_menu_bar(self) -> None:
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

    def _init_toolbars(self) -> None:
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

    def _init_central_widget(self) -> None:
        self.tab_widget = WorkspaceTabWidget()
        self.tab_widget.tabCloseRequested.connect(self.remove_tab)
        # タブ切り替え時にタイトルとプロパティの接続を更新
        self.tab_widget.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tab_widget)

    def _init_docks(self) -> None:
        # 素材棚サイドバーを構築
        self.shelf_dock = QDockWidget("素材棚", self)
        self.shelf_dock.setAllowedAreas(Qt.LeftDockWidgetArea)
        self.shelf_widget = AssetShelfWidget(self.asset_mgr)
        self.shelf_dock.setWidget(self.shelf_widget)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.shelf_dock)

        # 棚のアイテムがダブルクリックされたときの処理
        self.shelf_widget.assetSelected.connect(self.on_asset_from_shelf)

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

        # 表示メニューへの追加（menuBar()を再度取得）
        view_menu = self.menuBar().addMenu("表示")
        view_menu.addAction(self.dock.toggleViewAction())

        # プレビュー用のドックを追加
        self.preview_dock = QDockWidget("切り抜きプレビュー", self)
        self.preview_panel = PreviewPanel()
        self.preview_dock.setWidget(self.preview_panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.preview_dock)

        view_menu.addAction(self.preview_dock.toggleViewAction())

        # ドックの初期サイズ設定
        self.resizeDocks([self.dock, self.preview_dock], [300, 300], Qt.Vertical)

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
        self.template_toolbar.setEnabled(container.supports_template)

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
        self.prop_panel.set_target(item)

    def _handle_rects_changed(self, rects: List[object]) -> None:
        """信号の送信元が現在のタブの場合のみパネルを更新する"""
        self.prop_panel.update_list(rects)
        self.preview_panel.update_previews(self.current_view())

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
        """新しいタブを追加し、信号を接続してアクティブにする"""
        # 1. デスク工場で「すぐに使える状態」のインスタンスを取得
        new_desk = self._create_desk(desk_class)

        # 2. タブへの追加作業を専門家へ委譲（内部でタイトル計算、選択、UI同期が行われる）
        self.tab_widget.add_desk(new_desk)

        return new_desk

    def _create_desk(self, desk_class: Type[BaseDeskWidget]) -> BaseDeskWidget:
        """デスクウィジェットを生成し、シグナルを接続して返す（デスク工場）"""
        # 1. インスタンス化
        desk = desk_class(self.asset_mgr)

        # 2. シグナル接続（ハンドラへの紐付けを一箇所で管理）
        self._setup_desk_signals(desk)

        return desk

    def _setup_desk_signals(self, desk: BaseDeskWidget) -> None:
        """デスクウィジェットの各シグナルをMainWindowのハンドラに接続する"""
        desk.fileDropped.connect(self.load_new_pdf)
        desk.selectionChanged.connect(self._handle_selection_changed)
        desk.contentChanged.connect(self._handle_rects_changed)

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

    def remove_tab(self, index: int) -> None:
        """指定したインデックスのタブを閉じる"""
        self.tab_widget.removeTab(index)

        # 全てのタブが閉じられたら新しい空のタブを作る
        if self.tab_widget.count() == 0:
            self.add_new_tab()

    def open_file(self) -> None:
        """ファイル選択ダイアログを開き、選択されたPDFを素材棚に追加する"""
        filter_str = f"Supported Files ({' '.join(['*' + ext for ext in self.SUPPORTED_EXTENSIONS])})"
        file_path, _ = QFileDialog.getOpenFileName(self, "素材を追加", "", filter_str)
        if file_path:
            # マネージャーを通じて棚へ追加
            self.asset_mgr.create_source(file_path)

    def on_asset_from_shelf(self, asset_id: str) -> None:
        asset = self.asset_mgr.get_asset(asset_id)
        if asset:
            self.open_asset(asset)
        else:
            print(f"Asset {asset_id} not found")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            # 渡されたURL（ファイルパス）が対象ファイルかチェック
            for url in event.mimeData().urls():
                if self._is_supported_file(url.toLocalFile()):
                    event.acceptProposedAction()
                    return

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if self._is_supported_file(url.toLocalFile()):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if self._is_supported_file(file_path):
                self.load_new_pdf(file_path)
                break

    def _is_supported_file(self, file_path: str) -> bool:
        """指定されたファイルパスがサポートされている形式かチェックする"""
        return file_path.lower().endswith(self.SUPPORTED_EXTENSIONS)

    def load_new_pdf(self, file_path: str) -> None:
        """外部から持ち込まれたファイルを素材棚に登録し、そのままワークスペースで開く"""
        asset = self.asset_mgr.create_source(file_path)
        self.open_asset(asset)

    def open_asset(self, asset: WorkspaceAsset) -> None:
        """
        アセットを最適なデスク（タブ）に選別してロードし、UIの状態を更新する。
        （アセット・ロード・ルーティングの統合窓口）
        """
        desk = self.current_desk()

        # 現在のデスクがそのアセットを受け入れられない場合は、強制的に新規タブ扱いにする
        is_compatible = desk and desk.can_accept_asset(asset)

        if not is_compatible:
            # アセットの種類に応じてデフォルトのデスククラスを選択
            desk_class = DEFAULT_DESK_MAP.get(type(asset), CropDeskWidget)
            desk = self.add_new_tab(desk_class)

        # 2. ロード準備（デスク側の判断による破棄確認など）
        if not desk.is_ready_to_load():
            return

        # 3. アセットのロード実行
        desk.set_asset(asset)

        # 4. 事後処理：タブタイトルやウィンドウタイトルの更新を専門家へ通知
        self.tab_widget.update_desk_title(desk, asset.name)
        self.update_window_title()

    def process_crop(self) -> None:
        """現在のタブの種類に応じて、書き出し処理（クロップ保存またはPDF結合）を呼び出す"""
        desk = self.current_desk()
        if desk and hasattr(desk, "export_as_pdf"):
            desk.export_as_pdf()
        else:
            QMessageBox.warning(self, "警告", "書き出し可能なタブが開かれていません")
