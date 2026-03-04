from PySide6.QtGui import QUndoCommand


class AddCommand(QUndoCommand):
    """アイテム（単数または複数）をシーンに追加するコマンド"""

    def __init__(self, view, items, text="枠の追加"):
        super().__init__(text)
        self.view = view
        self.items = items if isinstance(items, list) else [items]

    def undo(self):
        for item in self.items:
            # リストにあれば削除
            if item in self.view.rects:
                self.view.rects.remove(item)
            # シーンにあれば削除
            if item.scene():
                self.view.scene.removeItem(item)
        self.view.update_numbers()
        self.view.rectsChanged.emit(self.view.rects)

    def redo(self):
        for item in self.items:
            # リストになければ追加
            if item not in self.view.rects:
                self.view.rects.append(item)
            # シーンになければ追加（ここでの重複チェックが重要）
            if not item.scene():
                self.view.scene.addItem(item)
        self.view.update_numbers()
        self.view.rectsChanged.emit(self.view.rects)


class RemoveCommand(QUndoCommand):
    """アイテム（単数または複数）をシーンから削除するコマンド"""

    def __init__(self, view, items, text="枠の削除"):
        super().__init__(text)
        self.view = view
        self.items = items if isinstance(items, list) else [items]

    def undo(self):
        for item in self.items:
            if item not in self.view.rects:
                self.view.rects.append(item)
            if not item.scene():
                self.view.scene.addItem(item)
        self.view.update_numbers()
        self.view.rectsChanged.emit(self.view.rects)

    def redo(self):
        for item in self.items:
            if item in self.view.rects:
                self.view.rects.remove(item)
            if item.scene():
                self.view.scene.removeItem(item)
        self.view.update_numbers()
        self.view.rectsChanged.emit(self.view.rects)


class TransformCommand(QUndoCommand):
    """
    アイテムの変形（位置・サイズ）を記録するコマンド。
    複数のアイテム（同期移動など）にも一括対応。
    """

    def __init__(self, view, transforms, text="移動/変形"):
        super().__init__(text)
        self.view = view
        self._transforms = (
            transforms  # list of (item, old_pos, old_rect, new_pos, new_rect)
        )

    def undo(self):
        for item, old_p, old_r, _, _ in self._transforms:
            item._block_sync = True  # ループ防止
            item.setPos(old_p)
            item.setRect(old_r)
            item._block_sync = False
        self.view.update_numbers()
        self.view.rectsChanged.emit(
            self.view.view_rects()
            if hasattr(self.view, "view_rects")
            else self.view.rects
        )

    def redo(self):
        for item, _, _, new_p, new_r in self._transforms:
            item._block_sync = True
            item.setPos(new_p)
            item.setRect(new_r)
            item._block_sync = False
        self.view.update_numbers()
        self.view.rectsChanged.emit(
            self.view.view_rects()
            if hasattr(self.view, "view_rects")
            else self.view.rects
        )


class ReorderCommand(QUndoCommand):
    """リストの順序変更のみを記録するコマンド"""

    def __init__(self, view, old_rects, new_rects, text="並び替え"):
        super().__init__(text)
        self.view = view
        self.old_rects = list(old_rects)
        self.new_rects = list(new_rects)

    def undo(self):
        self.view.rects = list(self.old_rects)
        self.view.update_numbers()
        self.view.rectsChanged.emit(self.view.rects)

    def redo(self):
        self.view.rects = list(self.new_rects)
        self.view.update_numbers()
        self.view.rectsChanged.emit(self.view.rects)
