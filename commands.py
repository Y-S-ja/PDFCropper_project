from PySide6.QtGui import QUndoCommand


class RectStateCommand(QUndoCommand):
    """
    枠の状態（全件スナップショット）を管理するコマンド。
    既存の _restore_state を利用して Undo/Redo を行います。
    """

    def __init__(self, view, old_state, new_state, text: str):
        super().__init__(text)
        self.view = view
        self.old_state = old_state
        self.new_state = new_state
        self._first_run = True

    def undo(self):
        """前の状態に戻す"""
        self.view._restore_state(self.old_state)

    def redo(self):
        """新しい状態にする（push時にも自動で呼ばれる）"""
        # 初回実行時（push時）は、すでにUI側で変更が完了していることが多いため、
        # 無駄な復元処理をスキップする工夫
        if self._first_run:
            self._first_run = False
            return
        self.view._restore_state(self.new_state)
