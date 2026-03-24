import os
from dataclasses import dataclass
from typing import Optional, List, Tuple
from PySide6.QtWidgets import (
    QPushButton,
    QMessageBox,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsItem,
    QFrame,
    QHBoxLayout,
)
from PySide6.QtCore import Qt, QRectF, Signal, QPointF, QPoint
from PySide6.QtGui import QPen, QColor, QBrush, QUndoStack
from graphics_items import myCropBox, myBadge, myIntroductionText, CandidateBox
from pdf_processor import PdfProcessor
from commands import AddCommand, RemoveCommand, TransformCommand, ReorderCommand
from interaction_modes import CropMode, CandidateSelectionMode


@dataclass
class HitTestResult:
    """マウス位置にあるアイテムの判定結果を保持するデータクラス"""

    item: Optional[QGraphicsItem] = None
    is_cropbox: bool = False
    is_intro_text: bool = False
    is_candidate: bool = False


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
        lambda self: self._state._rects,
        lambda self, v: setattr(self._state, "_rects", v),
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
    def _start_pos(self):
        return self._state._start_pos

    @_start_pos.setter
    def _start_pos(self, v):
        self._state._start_pos = v

    @property
    def _new_rect(self):
        return self._state._new_rect

    @_new_rect.setter
    def _new_rect(self, v):
        self._state._new_rect = v

    @property
    def _pre_action_states(self):
        return self._state._pre_action_states

    @_pre_action_states.setter
    def _pre_action_states(self, v):
        self._state._pre_action_states = v

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

    # --- コマンド実行用の低レベルAPI (Raw Operations) ---
    # これらは UndoStack 経由で呼び出されることを想定しており、
    # 実行時に新たな Undo コマンドを生成しない。

    def _raw_add_item(self, item, index: int):
        """アイテムをリストとシーンの指定位置に追加する"""
        if item not in self.rects:
            if index >= len(self.rects):
                self.rects.append(item)
            else:
                self.rects.insert(index, item)

        if not item.scene():
            self._scene.addItem(item)

        self.update_numbers()
        self.rectsChanged.emit(self.rects)

    def _raw_remove_item(self, item):
        """アイテムをリストとシーンから除外する"""
        if item in self.rects:
            self.rects.remove(item)

        if item.scene():
            self._scene.removeItem(item)

        self.update_numbers()
        self.rectsChanged.emit(self.rects)

    def _raw_apply_transforms(self, transforms):
        """複数のアイテムの変形を一括適用する"""
        # transforms: list of (item, _, _, new_pos, new_rect) or (item, old_pos, old_rect, _, _)
        for item, p, r in transforms:
            item._block_sync = True
            item.setRect(r)
            item.setPos(p)
            item._block_sync = False

        self.update_numbers()
        self.rectsChanged.emit(self.rects)
        self._on_scene_selection_changed()

    def _raw_reorder_rects(self, new_list):
        """リストの順序を書き換える"""
        self.rects = list(new_list)
        self.update_numbers()
        self.rectsChanged.emit(self.rects)

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

    def load_from_path(self, path: str):
        """パスからページを読み出し、デスクを初期化する"""
        self.pdf_path = path
        self.load_pdf_page(path)

    def restore_boxes(self, rects: list):
        """既存の切り抜き枠（QRectF）のリストを受け取り、myCropBoxとして画面に復元する"""
        self._scene.clearSelection()
        for r in rects:
            # QRectF のジオメトリから myCropBox インスタンスを生成
            box = myCropBox(r)
            box.confirmed = True
            box.tag = "selection_rect"
            box.rect_id = len(self.rects) + 1

            # イベントシグナルの接続
            box.geometryChanged.connect(self._handle_item_geometry_changed)
            box.deltaResized.connect(self._handle_item_delta_resized)
            box.transformationFinished.connect(self._handle_transformation_finished)

            # シーンとリストへ直接追加 (初期ロードのため Undo には積まない)
            self._raw_add_item(box, len(self.rects))

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

    def get_crop_coordinates(self) -> List[Tuple[float, float, float, float]]:
        """UI部品(myCropBox)から正規化された(シーン上の)座標リストを取得する"""
        coords = []
        for item in self.rects:
            s_rect = item.mapToScene(item.rect()).boundingRect()
            coords.append(
                (s_rect.left(), s_rect.top(), s_rect.right(), s_rect.bottom())
            )
        return coords

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
