from PySide6.QtGui import QUndoCommand


class AddCommand(QUndoCommand):
    """アイテム（単数または複数）をシーンに追加するコマンド"""

    def __init__(self, view, items, text="枠の追加"):
        super().__init__(text)
        self.view = view
        self.items = items if isinstance(items, list) else [items]
        # 追加位置を確定（現在の末尾）
        self.indices = [len(self.view.rects) + i for i in range(len(self.items))]

    def undo(self):
        self.view._raw_remove_items(self.items)

    def redo(self):
        # 最初のインデックスを指定して一括追加
        self.view._raw_add_items(self.items, self.indices[0] if self.indices else None)


class RemoveCommand(QUndoCommand):
    """アイテム（単数または複数）をシーンから削除するコマンド"""

    def __init__(self, view, items, text="枠の削除"):
        super().__init__(text)
        self.view = view
        self.items = items if isinstance(items, list) else [items]
        # 削除前のインデックスを記憶
        self.item_data = []
        for item in self.items:
            idx = self.view.rects.index(item) if item in self.view.rects else -1
            self.item_data.append((item, idx))

    def undo(self):
        # 元の位置に復元（インデックス順に一括処理するのは難しいため、一旦個別に戻すが、
        # もし重いようならここも最適化の余地あり。一旦は単純化して個別追加のままにするか、
        # あるいは連続したインデックスなら一括で行う）
        # 削除コマンドは通常「選択されたもの」を一括削除するので、戻す際も連続していることが多い。
        # ここでは一番シンプルな「個別に戻す」ままとし、redo側を一括にする。
        for item, idx in sorted(self.item_data, key=lambda x: x[1]):
            if idx != -1:
                self.view._raw_add_item(item, idx)

    def redo(self):
        self.view._raw_remove_items(self.items)


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
        data = [(item, old_p, old_r) for item, old_p, old_r, _, _ in self._transforms]
        self.view._raw_apply_transforms(data)

    def redo(self):
        data = [(item, new_p, new_r) for item, _, _, new_p, new_r in self._transforms]
        self.view._raw_apply_transforms(data)


class ReorderCommand(QUndoCommand):
    """リストの順序変更のみを記録するコマンド"""

    def __init__(self, view, old_rects, new_rects, text="並び替え"):
        super().__init__(text)
        self.view = view
        self.old_rects = list(old_rects)
        self.new_rects = list(new_rects)

    def undo(self):
        self.view._raw_reorder_rects(self.old_rects)

    def redo(self):
        self.view._raw_reorder_rects(self.new_rects)
