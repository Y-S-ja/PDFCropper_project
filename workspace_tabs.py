from PySide6.QtWidgets import QTabWidget


class WorkspaceTabWidget(QTabWidget):
    """
    ワークスペースのタブ一式を管理するカスタムタブウィジェット。
    タブの命名規則（プレフィックス）や連番の管理など、タブ固有の振る舞いを担当する。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)

    def generate_desk_title(self, desk_class) -> str:
        """デスクの種類に応じて、重複しない適切な連番付きタイトルを生成する"""
        class_name = desk_class.__name__
        if "Join" in class_name:
            prefix = "🔗_Join"
        elif "Organize" in class_name:
            prefix = "🗂️_Organize"
        else:
            prefix = "✂️_Crop"

        used_numbers = set()
        for i in range(self.count()):
            text = self.tabText(i)
            if text.startswith(f"{prefix} "):
                try:
                    num_str = text.split(" ")[1]
                    used_numbers.add(int(num_str))
                except (IndexError, ValueError):
                    pass

        new_num = 1
        while new_num in used_numbers:
            new_num += 1

        return f"{prefix} {new_num}"

    def add_desk(self, desk) -> int:
        """デスクを追加し、自動計算されたタイトルを割り当てる"""
        title = self.generate_desk_title(desk.__class__)
        index = self.addTab(desk, title)
        self.setCurrentIndex(index)
        return index

    def update_desk_title(self, desk, asset_name: str):
        """アセットがロードされた際、デスクの種類に応じてタイトルを更新する（名前の連動・固定ポリシーの集約）"""
        # ポリシー：同期フラグが立っているデスクのみ、連番タイトルの代わりにアセット名を優先する
        if getattr(desk, "sync_title_with_asset", False):
            index = self.indexOf(desk)
            if index != -1:
                self.setTabText(index, asset_name)
