import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Union
from PySide6.QtCore import QRectF, QObject, Signal


class WorkspaceAsset:
    """
    素材棚に並ぶ全てのアイテムの基底クラス。
    ID、名前、および中間生成物かどうかの属性を持つ。
    """

    def __init__(self, name: str):
        self.id = str(uuid.uuid4())
        self.name = name
        self.is_intermediate = False  # 加工品かどうかの識別

    def __repr__(self):
        return f"<{self.__class__.__name__} id={self.id[:6]} name={self.name}>"


class SourceAsset(WorkspaceAsset):
    """
    生のファイル（PDF/画像）を表すアセット。
    全ての加工の「根っこ（Root）」となる。
    """

    def __init__(self, name: str, path: str):
        super().__init__(name)
        self.path = path
        self.is_intermediate = False


class CroppedAsset(WorkspaceAsset):
    """
    既存のアセット（Source/Cropped/Joined）に対して
    一律の切り抜き枠（指示）を適用したアセット。
    """

    def __init__(self, name: str, parent: WorkspaceAsset, crop_rects: List[QRectF]):
        super().__init__(name)
        self.parent = parent
        self.crop_rects = crop_rects
        self.is_intermediate = True


class JoinedAsset(WorkspaceAsset):
    """
    複数のアセット（Source/Cropped/Joined）を
    特定の順序で繋ぎ合わせたアセット。
    """

    def __init__(self, name: str, items: List[WorkspaceAsset]):
        super().__init__(name)
        self.items = items
        self.is_intermediate = True


class AssetManager(QObject):
    """
    素材棚（Asset Shelf）のデータを一括管理・提供するマネージャー。
    """

    assets_changed = Signal()  # 素材の追加・削除・並び順の変更を通知

    def __init__(self):
        super().__init__()
        self._assets_dict: Dict[str, WorkspaceAsset] = {}
        self._order_ids: List[str] = []  # 棚の表示順

    def register_asset(self, asset: WorkspaceAsset):
        """アセットを管理下に登録し、棚の末尾に追加する。"""
        if asset.id not in self._assets_dict:
            self._assets_dict[asset.id] = asset
            self._order_ids.append(asset.id)
            self.assets_changed.emit()

    def unregister_asset(self, asset_id: str):
        """アセットを棚から削除する。"""
        if asset_id in self._assets_dict:
            del self._assets_dict[asset_id]
            if asset_id in self._order_ids:
                self._order_ids.remove(asset_id)
            self.assets_changed.emit()

    def get_asset(self, asset_id: str) -> Optional[WorkspaceAsset]:
        """IDからアセットを取得する。"""
        return self._assets_dict.get(asset_id)

    def all_assets(self) -> List[WorkspaceAsset]:
        """棚にある全アセットを表示順通りにリストで取得。"""
        return [self._assets_dict[aid] for aid in self._order_ids]

    def create_source(self, file_path: str):
        """外部ファイルから生の素材アセットを生成・登録する。"""
        import os

        name = os.path.basename(file_path)
        asset = SourceAsset(name, file_path)
        self.register_asset(asset)
        return asset

    def create_cropped(
        self, parent: WorkspaceAsset, crop_rects: List[QRectF], name: str = None
    ):
        """既存のアセットを切り抜いた中間生成物を生成・登録する。"""
        if not name:
            name = f"{parent.name}_cut"
        asset = CroppedAsset(name, parent, crop_rects)
        self.register_asset(asset)
        return asset

    def create_joined(self, asset_items: List[WorkspaceAsset], name: str = None):
        """複数のアセットを繋げた中間生成物を生成・登録する。"""
        if not name:
            name = " + ".join([it.name for it in asset_items])
        asset = JoinedAsset(name, asset_items)
        self.register_asset(asset)
        return asset
