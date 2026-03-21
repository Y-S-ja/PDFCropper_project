import sys
import os
from dataclasses import dataclass
from typing import Optional
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsItem,
    QTabWidget,
    QDockWidget,
    QStackedWidget,
    QFrame,
    QHBoxLayout,
)
from PySide6.QtCore import Qt, QRectF, Signal, QPointF, QPoint
from PySide6.QtGui import QPen, QColor, QBrush, QUndoStack, QAction
from myModule import myCropBox, myBadge, myIntroductionText, CandidateBox
from workspace_models import (
    AssetManager,
    SourceAsset,
    CroppedAsset,
    JoinedAsset,
    WorkspaceAsset,
)
from myDockContent import PreviewPanel, PropertyPanel, AssetShelfWidget
from pdf_processor import PdfProcessor
from commands import AddCommand, RemoveCommand, TransformCommand, ReorderCommand
from preview_view import PdfPreviewView


@dataclass
class HitTestResult:
    """マウス位置にあるアイテムの判定結果を保持するデータクラス"""

    item: Optional[QGraphicsItem] = None
    is_cropbox: bool = False
    is_intro_text: bool = False
    is_candidate: bool = False


class InteractionMode:
    """マウス操作モードの基底クラス"""

    def __init__(self, view):
        self.view = view

    def mousePress(self, event):
        # 動作確認用のデバッグ出力
        print(f"DEBUG: InteractionMode.mousePress (Mode: {self.__class__.__name__})")
        return False  # Falseを返すと既存のロジックを継続

    def mouseMove(self, event):
        return False

    def mouseRelease(self, event):
        return False

    def keyPress(self, event):
        return False

    def on_enter(self):
        pass

    def on_exit(self):
        pass


class DefaultMode(InteractionMode):
    """移行用のデフォルトモード"""

    pass


class CropMode(InteractionMode):
    """
    通常の切り抜き枠の作成、選択、移動、リサイズ、削除を行うモード
    """

    def mousePress(self, event):
        # 1. 判定（ViewのQueryを使う）
        res = self.view.hit_test(event.position().toPoint())

        # --- 右クリック：削除 ---
        if event.button() == Qt.RightButton:
            if res.is_cropbox:
                print("Right-clicked: CropBox (Deleting via NormalMode)")
                self.view.remove_box(res.item)
                return True
            elif res.is_intro_text:
                print("Right-clicked: Intro Text (Ignoring via NormalMode)")
                return True
            return False

        # --- 左クリック：操作 or 新規作成 ---
        if event.button() == Qt.LeftButton:
            # アクション開始前のアイテムの状態を個別に保持
            self.view.record_pre_transform_state()

            if res.is_cropbox:
                print(
                    f"Left-clicked: CropBox (ID:{res.item.rect_id}) (Resizing/Moving via NormalMode)"
                )
                # 親クラスのQGraphicsViewにイベントを届けるためにFalseを返して継続させる
                return False
            else:
                # --- 新規作成の開始判定 ---
                scene_pos = self.view.mapToScene(event.position().toPoint())
                if not self.view.is_in_active_area(scene_pos) or res.is_intro_text:
                    print("Left-clicked: Far Background (Ignoring via NormalMode)")
                    return True

                # 新規作成開始
                self.view.begin_box_drawing(event.position().toPoint())
                print("Starting to draw new rect via NormalMode")
                return True
        return False

    def mouseMove(self, event):
        # 新規枠作成中の更新（描画中でなければ内部で無視される）
        return self.view.update_box_drawing(event.position().toPoint())

    def mouseRelease(self, event):
        # 1. 新規描画の確定（描画中でなければ内部で無視される）
        if self.view.finish_box_drawing():
            # 完了時に True を返しているため、後続の移動確定をスキップしたくない場合はここで判定
            pass

        # 2. 移動・変形の確定
        self.view.commit_transformation("移動または変形")
        return False

    def keyPress(self, event):
        """方向キーによる枠の微調整ロジックを移動"""
        selected_items = self.view.selected_cropboxes()
        if not selected_items:
            return False

        step = 10 if event.modifiers() & Qt.ShiftModifier else 1
        dx, dy = 0, 0

        if event.key() == Qt.Key_Left:
            dx = -step
        elif event.key() == Qt.Key_Right:
            dx = step
        elif event.key() == Qt.Key_Up:
            dy = -step
        elif event.key() == Qt.Key_Down:
            dy = step
        else:
            return False

        # 移動前の状態を記録
        self.view.record_pre_transform_state()
        for item in selected_items:
            item.setPos(item.pos() + QPointF(dx, dy))

        # 移動後の状態を確認し、履歴にコミット
        self.view.commit_transformation("キー操作による移動")
        return True


class CandidateSelectionMode(InteractionMode):
    """自動認識された候補枠を選択するモード"""

    def __init__(self, view, candidate_items):
        super().__init__(view)
        self.candidate_items = candidate_items
        self.click_rotation_index = 0
        self.last_click_pos = QPointF()

    def on_enter(self):
        # 確定ボタンパネルを表示
        self.view.candidate_panel.show()

    def on_exit(self):
        # 確定ボタンパネルを非表示
        self.view.candidate_panel.hide()
        # 候補アイテムをクリーンアップ
        self.view.clear_candidates(self.candidate_items)
        self.candidate_items = []

    def mousePress(self, event):
        if event.button() == Qt.LeftButton:
            click_pos = event.position().toPoint()
            items = self.view.items(click_pos)
            candidates = [it for it in items if isinstance(it, CandidateBox)]

            if candidates:
                scene_pos = self.view.mapToScene(click_pos)
                if (scene_pos - self.last_click_pos).manhattanLength() < 5:
                    self.click_rotation_index = (self.click_rotation_index + 1) % len(
                        candidates
                    )
                else:
                    self.click_rotation_index = 0

                self.last_click_pos = scene_pos
                candidates[self.click_rotation_index].toggle()
                return True
        return False


class ProjectState:
    """プロジェクト（ファイル）ごとの編集状態を保持するコンテナ"""

    def __init__(self, view):
        self._pdf_item = None
        self._new_rect = None
        self._rects = []
        self._start_pos = None
        self._scale_factor = 1.0
        self._pdf_path = None
        self._current_page_index = 0
        self._rect_count = 0
        self._undo_stack = QUndoStack(view)
        self._pre_action_states = None


class PdfGraphicsView(QGraphicsView):
    fileDropped = Signal(str)
    selectionChanged = Signal(object)  # 選択されたアイテム(myCropBox)を通知用
    rectsChanged = Signal(list)  # 枠のリストが変更されたことを通知用

    # プロジェクト固有の変数をプロパティ経由で state へ中継 (外部公開が必要なものに限定)
    rects = property(
        lambda self: self._state._rects, lambda self, v: setattr(self._state, "_rects", v)
    )
    undo_stack = property(lambda self: self._state._undo_stack)
    pdf_path = property(
        lambda self: self._state._pdf_path,
        lambda self, v: setattr(self._state, "_pdf_path", v),
    )
    scale_factor = property(
        lambda self: self._state._scale_factor,
        lambda self, v: setattr(self._state, "_scale_factor", v),
    )
    current_page_index = property(
        lambda self: self._state._current_page_index,
        lambda self, v: setattr(self._state, "_current_page_index", v),
    )
    rect_count = property(
        lambda self: self._state._rect_count,
        lambda self, v: setattr(self._state, "_rect_count", v),
    )
    pdf_item = property(
        lambda self: self._state._pdf_item,
        lambda self, v: setattr(self._state, "_pdf_item", v),
    )

    # 内部管理用の変数をプライベートプロパティとして定義
    @property
    def _start_pos(self): return self._state._start_pos
    @_start_pos.setter
    def _start_pos(self, v): self._state._start_pos = v

    @property
    def _new_rect(self): return self._state._new_rect
    @_new_rect.setter
    def _new_rect(self, v): self._state._new_rect = v
    
    @property
    def _pre_action_states(self): return self._state._pre_action_states
    @_pre_action_states.setter
    def _pre_action_states(self, v): self._state._pre_action_states = v

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self._scene = None
        self._state = None
        self._current_mode = CropMode(self)  # 初期モードをNormalに変更
        self._setup_new_scene()

        # 2. 【魔法の設定】ズーム時の基準点を「マウスカーソルの下」にする
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        # キャンバスが画面より小さい時に中央に寄せる設定
        self.setAlignment(Qt.AlignCenter)

        # ドラッグでスクロールできるようにする設定をオフ（最初は普通のカーソルにする）
        self.setDragMode(QGraphicsView.NoDrag)
        # ビューポートのカーソルを十字（範囲選択っぽく）または標準に設定
        self.viewport().setCursor(Qt.CrossCursor)

        self.sync_size = True  # サイズ同期フラグ
        self.sync_symmetry = True  # 対称性同期フラグ

        # 初期メッセージを表示
        self.show_intro_message()

        # 確定ボタンパネル（ビューの右下に浮かせる）
        self.candidate_panel = QFrame(self)
        self.candidate_panel.setStyleSheet("""
            QFrame {
                background-color: rgba(255, 255, 255, 220);
                border: 1px solid #ccc;
                border-radius: 8px;
            }
            QPushButton {
                padding: 5px 15px;
                font-weight: bold;
                border-radius: 4px;
            }
            #confirmBtn { background-color: #4CAF50; color: white; }
            #confirmBtn:hover { background-color: #45a049; }
            #cancelBtn { background-color: #f44336; color: white; }
            #cancelBtn:hover { background-color: #da190b; }
        """)
        panel_layout = QHBoxLayout(self.candidate_panel)

        self.confirm_btn = QPushButton("✔ 選択した枠を確定", self.candidate_panel)
        self.confirm_btn.setObjectName("confirmBtn")
        self.confirm_btn.clicked.connect(self.confirm_candidates)

        self.cancel_btn = QPushButton("キャンセル", self.candidate_panel)
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.clicked.connect(self.cancel_candidates)

        panel_layout.addWidget(self.cancel_btn)
        panel_layout.addWidget(self.confirm_btn)

        self.candidate_panel.hide()

    def hit_test(self, pos: QPoint) -> HitTestResult:
        """指定された座標にあるアイテムの種類を判定する"""
        item = self.itemAt(pos)
        res = HitTestResult()
        if not item:
            return res

        # 親を辿って種類を特定
        temp = item
        while temp:
            if isinstance(temp, myCropBox):
                res.item = temp
                res.is_cropbox = True
                break
            if isinstance(temp, CandidateBox):
                res.item = temp
                res.is_candidate = True
                break
            if getattr(temp, "tag", temp.data(myCropBox.TAG_NAME)) == "intro_text":
                res.item = temp
                res.is_intro_text = True
                break
            temp = temp.parentItem()

        # アイテムが見つからなかったが何かはある場合（背景など）、生アイテムを保持
        if not res.item:
            res.item = item

        return res

    def is_in_active_area(self, scene_pos: QPointF) -> bool:
        """シーン座標が操作（新規作成など）可能な領域内にあるか判定"""
        pdf_rect = self.get_pdf_rect()
        if pdf_rect.isNull():
            return False

        snap_threshold = 30
        active_area = pdf_rect.adjusted(
            -snap_threshold, -snap_threshold, snap_threshold, snap_threshold
        )
        return active_area.contains(scene_pos)

    def begin_box_drawing(self, pos: QPoint):
        """新規枠の描画を開始する"""
        scene_pos = self.mapToScene(pos)
        self._start_pos = self.clamp_pos(scene_pos)

        self._scene.clearSelection()
        # 新規作成
        self._new_rect = myCropBox(QRectF(0, 0, 0, 0))
        self._new_rect.confirmed = False
        self._new_rect.setPos(self._start_pos)
        self._scene.addItem(self._new_rect)
        print(f"Drawing action started at {self._start_pos}")

    def update_box_drawing(self, pos: QPoint):
        """マウス位置に合わせて作成中の枠を更新する"""
        if not self._start_pos or not self._new_rect:
            return

        current_pos = self.clamp_pos(self.mapToScene(pos))
        diff = current_pos - self._start_pos
        actual_top_left = QPointF(
            min(self._start_pos.x(), current_pos.x()),
            min(self._start_pos.y(), current_pos.y()),
        )
        self._new_rect.setPos(actual_top_left)
        self._new_rect.setRect(QRectF(0, 0, abs(diff.x()), abs(diff.y())))

    def finish_box_drawing(self):
        """描画を確定し、正規のアイテムとして登録する"""
        if not self._start_pos or not self._new_rect:
            return True

        rect = self._new_rect.rect()

        # 【重要】小さすぎる枠（クリックミス等）は無視して削除する
        if rect.width() < 5 or rect.height() < 5:
            self._scene.removeItem(self._new_rect)
            print("Drawing canceled: rectangle too small.")
        else:
            self._new_rect.confirmed = True  # 確定状態にする
            self._new_rect.tag = "selection_rect"
            self.rect_count += 1
            self._new_rect.rect_id = self.rect_count

            # 同期信号の接続
            self._new_rect.geometryChanged.connect(self._handle_item_geometry_changed)
            self._new_rect.deltaResized.connect(self._handle_item_delta_resized)
            self._new_rect.transformationFinished.connect(
                self._handle_transformation_finished
            )

            # --- 番号表示 (バッジ) ---
            # AddCommand -> update_numbers() 内で最終的に再調整されるため、暫定的な番号を渡す
            index = len(self.rects) + 1
            badge = myBadge(index, parent=self._new_rect)
            badge.setPos(rect.topLeft())

            # 一旦シーンから除外してから、AddCommand 経由で公式に追加する
            self._scene.removeItem(self._new_rect)
            self.undo_stack.push(AddCommand(self, self._new_rect, "枠の作成"))

            # 新しく作った枠を選択状態にする
            self._scene.clearSelection()
            self._new_rect.setSelected(True)
            print(f"Drawing finished: Rect ID {self.rect_count} created.")

        self._start_pos = None
        self._new_rect = None
        return True

    def remove_box(self, box_item: myCropBox):
        """指定された枠を削除し、Undoスタックに登録する"""
        if not box_item:
            return
        self.undo_stack.push(RemoveCommand(self, box_item))

    def record_pre_transform_state(self):
        """現在の全枠の状態をバックアップする（Undo用）"""
        self._pre_action_states = self._get_rect_states_map()

    def commit_transformation(self, label="移動または変形"):
        """バックアップ時からの差分を確認し、変更があればUndoスタックに登録する"""
        if not self._pre_action_states:
            return

        new_states = self._get_rect_states_map()
        transforms = []
        for item, (old_p, old_r) in self._pre_action_states.items():
            if item in new_states:
                new_p, new_r = new_states[item]
                if old_p != new_p or old_r != new_r:
                    transforms.append((item, old_p, old_r, new_p, new_r))

        if transforms:
            self.undo_stack.push(TransformCommand(self, transforms, label))

        self._pre_action_states = None
        self._start_pos = None

    def selected_cropboxes(self) -> list:
        """選択されている切り抜き枠のリストを返す"""
        return [i for i in self._scene.selectedItems() if isinstance(i, myCropBox)]

    def clear_candidates(self, item_list):
        """指定された候補アイテムをシーンから一括削除する"""
        for item in item_list:
            if item.scene():
                self._scene.removeItem(item)

    def set_interaction_mode(self, mode_class, *args, **kwargs):
        """操作モードを切り替える"""
        if self._current_mode:
            self._current_mode.on_exit()
        self._current_mode = mode_class(self, *args, **kwargs)
        self._current_mode.on_enter()
        print(f"MODE CHANGED: {self._current_mode.__class__.__name__}")

    def _reset_project_state(self):
        """プロジェクト固有の変数を機械的に一括初期化する"""
        if hasattr(self, "_state") and self._state:
            self._state._undo_stack.deleteLater()  # 旧スタックの明示的破棄
        self._state = ProjectState(self)

    def _setup_new_scene(self):
        """新しいシーンを作成し、インフラを再構築して古いシーンを破棄する"""
        self._reset_project_state()
        new_scene = QGraphicsScene(self)
        new_scene.setBackgroundBrush(QBrush(QColor("lightgray")))
        new_scene.selectionChanged.connect(self._on_scene_selection_changed)

        # 基礎設定
        self.margin = 100
        self.canvas_rect = QRectF(0, 0, 800, 600)
        new_scene.setSceneRect(self.canvas_rect)

        # キャンバス枠の設置
        self.field_rect = QGraphicsRectItem(self.canvas_rect)
        new_scene.addItem(self.field_rect)

        # シーンの差し替え
        old_scene = getattr(self, "_scene", None)
        self.setScene(new_scene)
        self._scene = new_scene

        if old_scene:
            old_scene.deleteLater()

    def detectItemByTag(self, tag):
        for item in self._scene.items():
            # プロパティがあれば使い、なければ data() から取得する
            if getattr(item, "tag", item.data(myCropBox.TAG_NAME)) == tag:
                return item
        return None

    def update_scene_limit(self):
        """シーンの範囲を現在のアイテム（主にPDF）に合わせる"""
        if hasattr(self, "pdf_item") and self.pdf_item:
            self._scene.setSceneRect(
                self.pdf_item.boundingRect().adjusted(
                    -self.margin, -self.margin, self.margin, self.margin
                )
            )
        else:
            self._scene.setSceneRect(QRectF(0, 0, 800, 600))

    def drawForeground(self, painter, rect):
        """キャンバス領域（canvas_rect）に枠線を描画"""
        if hasattr(self, "canvas_rect") and not self.canvas_rect.isNull():
            pen = QPen(QColor(150, 150, 150), 1.5, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self._scene.sceneRect())

    def center_A_on_B(self, A, B):
        br = A.boundingRect()
        A.setPos(
            (B.rect().width() - br.width()) / 2, (B.rect().height() - br.height()) / 2
        )

    def show_intro_message(self):
        """起動時のメッセージを表示"""
        # self._scene.clear()

        text = myIntroductionText("PDFファイルをここにドラッグ＆ドロップしてください")
        self._scene.addItem(text)
        text.setBrush(QBrush(QColor("gray")))
        font = text.font()
        font.setPointSize(18)
        text.setFont(font)
        # 案内テキストであることを識別するためのタグを付ける
        text.tag = "intro_text"
        self.center_A_on_B(text, self.field_rect)

    def load_pdf_page(self, file_path):
        if not os.path.exists(file_path):
            print(f"❌ ファイルが見つかりません: {file_path}")
            return

        # 1. 共通処理でシーンとステートを刷新
        self._setup_new_scene()

        self.rectsChanged.emit(self.rects)
        self.pdf_path = file_path

        # 6. PDF読み込み
        try:
            pixmap, original_width = PdfProcessor.get_page_image(file_path)
            print(f"pdf_image created: {pixmap}")
            # シーンに画像を追加
            self.pdf_item = self._scene.addPixmap(pixmap)
            print("pdf_item added to new scene")
        except Exception as e:
            print(f"❌ PDFの読み込みに失敗しました: {e}")
            return

        # PDF本来のサイズとの比率を計算（これが唯一の計算）
        self.scale_factor = original_width / pixmap.width()

        # 最初の表示を小さくする（0.4倍）
        self.resetTransform()
        self.scale(0.4, 0.4)

        self.update_scene_limit()
        # 読み込み直後に、ビューの中心をキャンバスの中央に合わせる
        self.centerOn(self.pdf_item.boundingRect().center())

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

    def keyPressEvent(self, event):
        # モードへの委譲
        if self._current_mode.keyPress(event):
            return

        super().keyPressEvent(event)

    def get_pdf_rect(self):
        """PDF画像のシーン座標での矩形を返す"""
        if hasattr(self, "pdf_item") and self.pdf_item:
            return self.pdf_item.boundingRect()
        return self.sceneRect()

    def clamp_pos(self, pos):
        """座標をPDFの範囲内に収める"""
        r = self.get_pdf_rect()
        x = max(r.left(), min(pos.x(), r.right()))
        y = max(r.top(), min(pos.y(), r.bottom()))
        return QPointF(x, y)

    def resizeEvent(self, event):
        """ウィンドウサイズ変更時にボタン位置を調整"""
        super().resizeEvent(event)
        self.update_candidate_panel_pos()

    def update_candidate_panel_pos(self):
        """候補選択パネルを右下に配置"""
        if self.candidate_panel.isVisible():
            margin = 20
            x = self.width() - self.candidate_panel.width() - margin
            y = self.height() - self.candidate_panel.height() - margin
            self.candidate_panel.move(x, y)

    def _get_rect_states_map(self):
        """現在の全枠のインスタンスと（座標・サイズ）のペアを返す"""
        return {item: (QPointF(item.pos()), QRectF(item.rect())) for item in self.rects}

    def mousePressEvent(self, event):
        # モードへの委譲
        if self._current_mode.mousePress(event):
            return

        super().mousePressEvent(event)

    def mousePressEvent_LegacyCleanup(self):
        # このチャンクで古い不要な判定フェーズ～新規作成ロジックを削除
        pass

    def ask_discard_changes(self) -> bool:
        """未保存の枠がある場合、破棄していいか確認する"""
        if self.rects:
            ret = QMessageBox.question(
                self,
                "確認",
                "編集中の枠が破棄されますが、新しいファイルを開きますか？\n（保存されていない変更は失われます）",
                QMessageBox.Yes | QMessageBox.No,
            )
            return ret == QMessageBox.Yes
        return True

    def set_asset(self, asset: WorkspaceAsset):
        """アセットを読み込み、デスクを初期化する"""
        if not asset or not isinstance(asset, SourceAsset):
            # 現時点ではSourceのみ対応
            print(f"Asset {asset} is not a SourceAsset")
            return

        self.pdf_path = asset.path
        self.load_pdf_page(asset.path)
        # TODO: asset に既に切り抜き指示があれば読み込む機能をフェーズ3で実装

    def mouseMoveEvent(self, event):
        # モードへの委譲
        if self._current_mode.mouseMove(event):
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # モードへの委譲
        if self._current_mode.mouseRelease(event):
            return

        super().mouseReleaseEvent(event)
        self.update_scene_limit()
        if self._pre_action_states is not None:
            new_states = self._get_rect_states_map()
            transforms = []
            for item, (old_p, old_r) in self._pre_action_states.items():
                if item in new_states:
                    new_p, new_r = new_states[item]
                    if old_p != new_p or old_r != new_r:
                        transforms.append((item, old_p, old_r, new_p, new_r))

            if transforms:
                self.undo_stack.push(
                    TransformCommand(self, transforms, "枠の移動/変形")
                )

            self._pre_action_states = None

        self.update_scene_limit()

    def update_numbers(self):
        """残っている枠の番号を1から順に振り直す。また、切り抜き順に合わせてZValue（重なり順）も更新する。"""
        for i, item in enumerate(self.rects):
            # 重なり順を更新（後の番号ほど上に表示されるようにする）
            item.setZValue(i)
            # 見た目の番号（バッジ）のみを更新（IDは変えない）
            item.update_display_number(i + 1)

    def _on_scene_selection_changed(self):
        """シーンの選択が変更されたら、選択中の myCropBox をシグナルで飛ばす"""
        items = self._scene.selectedItems()
        target = None
        if items and isinstance(items[0], myCropBox):
            target = items[0]
        self.selectionChanged.emit(target)

    def get_snapshot(self):
        """座標、サイズ、および固有ID、同期用IDを含めたスナップショットを取る"""
        return [
            (
                item.rect_id,
                QPointF(item.pos()),
                QRectF(item.rect()),
                item.group_id,
                item.quadrant_id,
            )
            for item in self.rects
        ]

    def undo(self):
        """ひとつ前の状態に戻す"""
        self.undo_stack.undo()

    def redo(self):
        """戻した操作をやり直す"""
        self.undo_stack.redo()

    def _restore_state(self, state):
        """指定されたスナップショットから状態を復元する（共通処理）"""
        # ID（rect_id）をキーにした現在のアイテムの辞書を作成
        current_items = {item.rect_id: item for item in self.rects}

        # ハイブリッド更新：個数が同じなら座標・サイズの上書きと並び順の復元
        if len(state) == len(self.rects):
            new_rects_list = []
            for res_id, pos, rect, group_id, quad_id in state:
                item = current_items.get(res_id)
                if item:
                    item.setPos(pos)
                    item.setRect(rect)
                    item.group_id = group_id
                    item.quadrant_id = quad_id
                    new_rects_list.append(item)
            self.rects = new_rects_list
        else:
            # 個数が違う（追加や削除）場合は、全作成しなおす
            # 1. 現在の全アイテムをシーンから除去
            for item in self.rects:
                self._scene.removeItem(item)
            self.rects.clear()

            # 2. 保存されていた状態からアイテムを再作成
            for res_id, pos, rect, group_id, quad_id in state:
                box = myCropBox(rect)
                box.setPos(pos)

                # スタイル設定
                pen = QPen(QColor(0, 120, 215), 3)
                pen.setCosmetic(True)
                box.setPen(pen)
                box.setBrush(QBrush(QColor(0, 120, 215, 40)))

                # タグと固有IDを復元
                box.tag = "selection_rect"
                box.rect_id = res_id
                box.group_id = group_id
                box.quadrant_id = quad_id

                box.geometryChanged.connect(self._handle_item_geometry_changed)
                box.deltaResized.connect(self._handle_item_delta_resized)
                box.transformationFinished.connect(self._handle_transformation_finished)

                self._scene.addItem(box)
                self.rects.append(box)

                # バッジ（番号）の追加
                badge = myBadge(len(self.rects), parent=box)
                badge.setPos(rect.topLeft())

        # 3. 各種表示の更新
        self.update_numbers()
        self.rectsChanged.emit(self.rects)
        self._on_scene_selection_changed()

    def clear_selections(self):
        # 削除コマンドを積む
        if self.rects:
            self.undo_stack.push(RemoveCommand(self, list(self.rects), "全削除"))

        self.new_rect = None
        self.update_scene_limit()
        self._on_scene_selection_changed()

    def reorder_rects(self, new_order_objs):
        """プロパティパネルでの並び替えを反映する"""
        if self.rects == new_order_objs:
            return

        # 差分コマンドを積む
        self.undo_stack.push(ReorderCommand(self, self.rects, new_order_objs))

    def _handle_item_geometry_changed(self, item):
        """アイテムの確定後（移動終了時など）の同期"""
        if not self.sync_size and not self.sync_symmetry:
            return

        group_id = item.group_id
        if group_id is None:
            return

        # 変形中（リサイズ中）は deltaResized 側で処理するためスキップ
        if hasattr(item, "active_handle") and item.active_handle is not None:
            return

        # 移動同期などを行う
        self._sync_group(item, group_id)

    def _handle_transformation_finished(self, item):
        """アイテムの変形（リサイズ）が完了した時のクリーンアップ"""
        group_id = item.group_id
        if group_id is None:
            return

        # 自分以外のグループ全員を normalize する
        # (自分自身は mouseReleaseEvent 内ですでに normalize 済みのため)
        for rect in self.rects:
            if rect != item and rect.group_id == group_id:
                rect._block_sync = True
                rect.normalize_geometry()
                rect._block_sync = False

    def _handle_item_delta_resized(self, item, handle_id, delta_scene):
        """アイテムの変形中（ドラッグ中）のリアルタイム同期"""
        if not self.sync_size and not self.sync_symmetry:
            return
        group_id = item.group_id
        if group_id is not None:
            self._sync_group_delta(item, group_id, handle_id, delta_scene)

    def _sync_group_delta(self, source_item, group_id, handle_id, delta_scene):
        """同じグループの他のアイテムを変形同期させる"""
        s_quad = source_item.quadrant_id
        for rect in self.rects:
            if rect == source_item:
                continue
            if rect.group_id == group_id:
                rect._block_sync = True

                # 1. 対称性（位置）同期
                if self.sync_symmetry:
                    if not self.pdf_item:
                        rect._block_sync = False
                        continue

                    t_quad = rect.quadrant_id
                    target_handle = handle_id
                    target_delta = QPointF(delta_scene)

                    # Quadrant属性のビット差分でミラー判定 (0bit目が違う=横ミラー, 1bit目が違う=縦ミラー)
                    if s_quad is not None and t_quad is not None:
                        if (s_quad & 1) != (t_quad & 1):  # 横ミラー
                            target_handle ^= 1
                            target_delta.setX(-delta_scene.x())
                        if (s_quad & 2) != (t_quad & 2):  # 縦ミラー
                            target_handle ^= 2
                            target_delta.setY(-delta_scene.y())

                    if self.sync_size:
                        rect.apply_delta(target_handle, target_delta)

                elif self.sync_size:
                    rect.apply_delta(handle_id, delta_scene)

                rect._block_sync = False

    def _sync_group(self, source_item, group_id):
        """同じグループの他のアイテムを同期させる（最終確定時の絶対座標同期）"""
        s_quad = source_item.quadrant_id
        s_rect = source_item.rect()
        s_scene_rect = source_item.scene_rect

        for rect in self.rects:
            if rect == source_item:
                continue
            if rect.group_id == group_id:
                rect._block_sync = True

                # 1. サイズ同期
                if self.sync_size:
                    rect.setRect(s_rect)

                # 2. 対称性（位置）同期
                if self.sync_symmetry:
                    if not self.pdf_item:
                        rect._block_sync = False
                        continue
                    canvas_rect = self.pdf_item.pixmap().rect()
                    cw, ch = canvas_rect.width(), canvas_rect.height()

                    t_quad = rect.quadrant_id
                    target_scene_tl = QPointF()

                    if s_quad is not None and t_quad is not None:
                        # X方向のミラー判定
                        if (s_quad & 1) != (t_quad & 1):  # 左右反対
                            target_scene_tl.setX(cw - s_scene_rect.right())
                        else:  # 左右同じ
                            target_scene_tl.setX(s_scene_rect.left())

                        # Y方向のミラー判定
                        if (s_quad & 2) != (t_quad & 2):  # 上下反対
                            target_scene_tl.setY(ch - s_scene_rect.bottom())
                        else:  # 上下同じ
                            target_scene_tl.setY(s_scene_rect.top())
                    else:
                        # 属性がない場合のフォールバック（従来どおり）
                        target_scene_tl = s_scene_rect.topLeft()

                    # ターゲット枠への適用
                    rect.setPos(target_scene_tl - rect.rect().topLeft())

                rect._block_sync = False

    def add_template_boxes(self, data_list):
        """複数の矩形と制限領域をセットで追加する"""
        if not data_list:
            return

        created_boxes = []

        # グループIDを生成（現在の時刻などをベースにユニークな値にする）
        import time

        group_id = int(time.time() * 1000)

        for qrect, allowed_rect, quad_id in data_list:
            pos = qrect.topLeft()
            size_rect = QRectF(0, 0, qrect.width(), qrect.height())

            box = myCropBox(size_rect)
            box.setPos(pos)
            box.allowed_rect = allowed_rect  # ここでエリア制限を設定

            # スタイル設定
            pen = QPen(QColor(0, 120, 215), 3)
            pen.setCosmetic(True)
            box.setPen(pen)
            box.setBrush(QBrush(QColor(0, 120, 215, 40)))

            box.tag = "selection_rect"
            self.rect_count += 1
            box.rect_id = self.rect_count
            box.group_id = group_id
            box.quadrant_id = quad_id

            # 同期信号の接続
            box.geometryChanged.connect(self._handle_item_geometry_changed)
            box.deltaResized.connect(self._handle_item_delta_resized)
            box.transformationFinished.connect(self._handle_transformation_finished)

            # 暫定的な番号
            temp_idx = len(self.rects) + len(created_boxes) + 1
            badge = myBadge(temp_idx, parent=box)
            badge.setPos(size_rect.topLeft())

            created_boxes.append(box)

        # 全ての管理は AddCommand に任せる。
        # ここでは addItem や rects.append は一切行わない。
        self.undo_stack.push(AddCommand(self, created_boxes, "テンプレートの追加"))

    def add_template_2v(self):
        """2分割（縦）テンプレート"""
        if not self.pdf_item:
            return

        # ページの画像サイズを取得
        canvas_rect = self.pdf_item.pixmap().rect()
        w = canvas_rect.width()
        h = canvas_rect.height()

        # (初期位置, 制限領域, quad_id)
        # quad: 0=TL, 1=TR
        data = [
            (QRectF(0, 0, w / 2, h), QRectF(0, 0, w / 2, h), 0),
            (QRectF(w / 2, 0, w / 2, h), QRectF(w / 2, 0, w / 2, h), 1),
        ]
        self.add_template_boxes(data)

    def add_template_2h(self):
        """2分割（横）テンプレート"""
        if not self.pdf_item:
            return
        canvas_rect = self.pdf_item.pixmap().rect()
        w = canvas_rect.width()
        h = canvas_rect.height()

        # quad: 0=TL, 2=BL
        data = [
            (QRectF(0, 0, w, h / 2), QRectF(0, 0, w, h / 2), 0),
            (QRectF(0, h / 2, w, h / 2), QRectF(0, h / 2, w, h / 2), 2),
        ]
        self.add_template_boxes(data)

    def add_template_4(self):
        """4分割テンプレート"""
        if not self.pdf_item:
            return
        r = self.pdf_item.pixmap().rect()
        w, h = r.width(), r.height()
        cx, cy = w / 2, h / 2

        # quad: 0=TL, 1=TR, 2=BL, 3=BR
        data = [
            (QRectF(0, 0, cx, cy), QRectF(0, 0, cx, cy), 0),
            (QRectF(cx, 0, cx, cy), QRectF(cx, 0, cx, cy), 1),
            (QRectF(0, cy, cx, cy), QRectF(0, cy, cx, cy), 2),
            (QRectF(cx, cy, cx, cy), QRectF(cx, cy, cx, cy), 3),
        ]
        self.add_template_boxes(data)

    def auto_detect_frames(self):
        """現在のページから枠線を自動検知して候補を表示する"""
        if not self.pdf_path:
            return

        # 前回の候補があればクリア
        self.cancel_candidates()

        # 1. 枠線の検知
        pdf_rects = PdfProcessor.detect_frames(self.pdf_path, self.current_page_index)

        if not pdf_rects:
            QMessageBox.information(
                self, "情報", "このページにはベクター形式の枠線が見つかりませんでした。"
            )
            return

        # 2. 面積（シーン上のピクセル数）に基づいてソート
        # 候補表示用データのリストを作成 [(area, x, y, w, h), ...]
        rect_data = []
        for x0, y0, x1, y1 in pdf_rects:
            w = (x1 - x0) / self.scale_factor
            h = (y1 - y0) / self.scale_factor
            rect_data.append(
                (w * h, x0 / self.scale_factor, y0 / self.scale_factor, w, h)
            )

        # 面積の降順（大きい順）にソート。後で ZValue を設定する際
        # 大きいものほど ZValue を低く、小さいものほど ZValue を高くするため。
        rect_data.sort(key=lambda x: x[0], reverse=True)

        # 3. 候補表示用アイテムを作成
        candidates = []
        base_z = 100
        for i, (area, x, y, w, h) in enumerate(rect_data):
            c_box = CandidateBox(QRectF(0, 0, w, h))
            c_box.setPos(x, y)
            c_box.setZValue(base_z + (i * 0.1))
            self._scene.addItem(c_box)
            candidates.append(c_box)

        # 4. モードを切り替え（パネル表示などもモード側で制御）
        self.set_interaction_mode(CandidateSelectionMode, candidates)
        self.setDragMode(QGraphicsView.NoDrag)
        self.viewport().setCursor(Qt.ArrowCursor)

    def confirm_candidates(self):
        """採用された候補を確定して cropbox に変換する"""
        if not isinstance(self._current_mode, CandidateSelectionMode):
            return

        new_boxes = []
        # モードが保持している candidate_items を参照
        for c_box in self._current_mode.candidate_items:
            if c_box.is_active:
                # 正規の myCropBox に変換
                r = c_box.rect()
                box = myCropBox(r)
                box.setPos(c_box.pos())

                box.tag = "selection_rect"
                self.rect_count += 1
                box.rect_id = self.rect_count

                # 信号の接続
                box.geometryChanged.connect(self._handle_item_geometry_changed)
                box.deltaResized.connect(self._handle_item_delta_resized)
                box.transformationFinished.connect(self._handle_transformation_finished)

                # 番号バッジ
                idx = len(self.rects) + len(new_boxes) + 1
                badge = myBadge(idx, parent=box)
                badge.setPos(r.topLeft())

                new_boxes.append(box)

        # 履歴に追加
        if new_boxes:
            self.undo_stack.push(AddCommand(self, new_boxes, "枠線の自動認識"))

        # モードを切り替えることで後片付け（on_exit）が走る
        self.set_interaction_mode(CropMode)

    def cancel_candidates(self):
        """候補選択を中止して破棄する"""
        # モードを切り替えることで後片付け（on_exit）が走る
        self.set_interaction_mode(CropMode)


class PdfTabContainer(QStackedWidget):
    """
    1つのタブ内で「編集画面」と「プレビュー画面」を管理するコンテナ。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = PdfGraphicsView()
        self.preview = PdfPreviewView()

        self.addWidget(self.editor)
        self.addWidget(self.preview)

    def set_mode(self, preview_mode: bool):
        """表示モードを切り替える"""
        if preview_mode:
            # UIを即座に切り替えてから生成を開始
            self.setCurrentWidget(self.preview)
            self.preview.update_previews(
                self.editor.pdf_path, self.editor.rects, self.editor.scale_factor
            )
        else:
            # 編集に戻る際は生成を止める
            self.preview.stop_rendering()
            self.setCurrentWidget(self.editor)

    def is_preview_mode(self):
        return self.currentWidget() == self.preview


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

    def _apply_template_2v(self):
        view = self.current_view()
        if view:
            view.add_template_2v()

    def _apply_template_2h(self):
        view = self.current_view()
        if view:
            view.add_template_2h()

    def _apply_template_4(self):
        view = self.current_view()
        if view:
            view.add_template_4()

    def _handle_auto_detect(self):
        view = self.current_view()
        if view:
            view.auto_detect_frames()

    def _on_tab_changed(self, index):
        """タブが切り替わったら、現在のビューの選択状態をパネルに繋ぎ変える"""
        self.update_window_title()
        container = self.current_tab_container()
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

    def _handle_mode_change(self, preview_mode):
        """ツールバーでのモード切替を処理"""
        container = self.current_tab_container()
        if container:
            container.set_mode(preview_mode)
            self.action_editor.setChecked(not preview_mode)
            self.action_preview.setChecked(preview_mode)

    def _handle_selection_changed(self, item):
        """信号の送信元が現在のタブの場合のみパネルを更新する"""
        if self.sender() == self.current_view():
            self.prop_panel.set_target(item)

    def _handle_rects_changed(self, rects):
        """信号の送信元が現在のタブの場合のみパネルを更新する"""
        view = self.current_view()
        if self.sender() == view:
            self.prop_panel.update_list(rects)
            self.preview_panel.update_previews(view)

    def _handle_reorder(self, new_order):
        """ドックでの並び替えを現在のビューに反映する"""
        view = self.current_view()
        if view:
            view.reorder_rects(new_order)
            self.preview_panel.update_previews(view)

    def _handle_sync_size_changed(self, enabled):
        view = self.current_view()
        if view:
            view.sync_size = enabled

    def _handle_sync_symmetry_changed(self, enabled):
        view = self.current_view()
        if view:
            view.sync_symmetry = enabled

    def current_tab_container(self):
        return self.tab_widget.currentWidget()

    def current_view(self):
        container = self.current_tab_container()
        return container.editor if container else None

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

        new_container = PdfTabContainer()
        new_view = new_container.editor
        new_view.fileDropped.connect(self.load_new_pdf)
        # 信号を一度だけ中継用メソッドに接続する（disconnect不要にするため）
        new_view.selectionChanged.connect(self._handle_selection_changed)
        new_view.rectsChanged.connect(self._handle_rects_changed)

        index = self.tab_widget.addTab(new_container, f"無題 {new_num}")
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
        self.tab_widget.removeTab(index)

        # 全てのタブが閉じられたら新しい空のタブを作る
        if self.tab_widget.count() == 0:
            self.add_new_tab()

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "素材を追加", "", "PDF/Image Files (*.pdf *.png *.jpg *.jpeg *.bmp)"
        )
        if file_path:
            # マネージャーを通じて棚へ追加
            self.asset_mgr.create_source(file_path)

    def on_asset_from_shelf(self, asset_id: str):
        asset = self.asset_mgr.get_asset(asset_id)
        if not asset:
            print(f"Asset {asset_id} not found")
            return

        # 切り抜きデスク（現在は一画面なのでgraphics_view）
        view = self.current_view()
        if not view:
            print("No view found")
            return

        # 安全確認をしてからロード
        if view.ask_discard_changes():
            print(f"Loading asset {asset.path}")
            view.set_asset(asset)
            # 名前の同期
            current_index = self.tab_widget.currentIndex()
            self.tab_widget.setTabText(current_index, asset.name)
            self.update_window_title()

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
        if not view:
            return

        view.load_pdf_page(file_path)
        # タブの名前をファイル名に変える
        current_index = self.tab_widget.currentIndex()
        self.tab_widget.setTabText(current_index, os.path.basename(file_path))
        # ウィンドウタイトルも更新
        self.update_window_title()

    def process_crop(self):
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
