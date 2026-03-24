from PySide6.QtCore import Qt, QPointF
from graphics_items import CandidateBox


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
