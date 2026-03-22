import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Union
from PySide6.QtCore import QRectF, QObject, Signal


class WorkspaceAsset:
    """
    素材棚に並ぶ全てのアイテムの基底クラス。
    """

    def __init__(self, name: str, asset_id: str = None):
        self.id = asset_id if asset_id else str(uuid.uuid4())
        self.name = name
        self.is_intermediate = False  # 加工品かどうかの識別
        self.is_visible = True  # 棚に表示するかどうか

    def to_dict(self) -> dict:
        """JSONシリアライズ用の辞書形式に変換"""
        return {
            "type": self.__class__.__name__,
            "id": self.id,
            "name": self.name,
            "is_intermediate": self.is_intermediate,
            "is_visible": self.is_visible,
        }

    @classmethod
    def from_dict(cls, data: dict):
        """辞書形式からアセットを復元（各子クラスでオーバーライド）"""
        pass

    def __repr__(self):
        return f"<{self.__class__.__name__} id={self.id[:6]} name={self.name}>"


class SourceAsset(WorkspaceAsset):
    """
    生のファイル（PDF/画像）を表すアセット。
    """

    def __init__(self, name: str, path: str, asset_id: str = None):
        super().__init__(name, asset_id)
        self.path = path
        self.is_intermediate = False

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["path"] = self.path
        return d

    @classmethod
    def from_dict(cls, data: dict):
        return cls(data["name"], data["path"], data["id"])


class CroppedAsset(WorkspaceAsset):
    """
    既存のアセットに対して切り抜き枠（レシピ）を適用したアセット。
    """

    def __init__(
        self,
        name: str,
        parent_id: str,
        crop_rects: List[QRectF],
        scale_factor: float = 1.0,  # シーン座標からPDF座標への変換係数
        asset_id: str = None,
    ):
        super().__init__(name, asset_id)
        self.parent_id = parent_id
        self.crop_rects = crop_rects
        self.scale_factor = scale_factor
        self.is_intermediate = True

    def _rect_to_list(self, rect: QRectF) -> list:
        return [rect.x(), rect.y(), rect.width(), rect.height()]

    @staticmethod
    def _list_to_rect(rect_list: list) -> QRectF:
        return QRectF(rect_list[0], rect_list[1], rect_list[2], rect_list[3])

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["parent_id"] = self.parent_id
        d["crop_rects"] = [self._rect_to_list(rect) for rect in self.crop_rects]
        d["scale_factor"] = self.scale_factor
        return d

    @classmethod
    def from_dict(cls, data: dict):
        rects = [cls._list_to_rect(rect) for rect in data["crop_rects"]]
        return cls(
            data["name"],
            data["parent_id"],
            rects,
            data.get("scale_factor", 1.0),
            data["id"],
        )


class JoinedAsset(WorkspaceAsset):
    """
    複数のアセットを特定の順序で繋ぎ合わせたアセット。
    IDベースでリストを保持し、循環参照を防ぐ。
    """

    def __init__(self, name: str, item_ids: List[str], asset_id: str = None):
        super().__init__(name, asset_id)
        self.item_ids = item_ids
        self.is_intermediate = True

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["item_ids"] = self.item_ids
        return d

    @classmethod
    def from_dict(cls, data: dict):
        return cls(data["name"], data["item_ids"], data["id"])


class AssetManager(QObject):
    """
    素材棚（Asset Shelf）のデータを一括管理・シリアライズするマネージャー。
    """

    assets_changed = Signal()

    def __init__(self):
        super().__init__()
        self._assets_dict: Dict[str, WorkspaceAsset] = {}
        self._order_ids: List[str] = []

    def register_asset(self, asset: WorkspaceAsset):
        """アセットを管理下に登録し、棚の末尾に追加する。"""
        if asset.id not in self._assets_dict:
            self._assets_dict[asset.id] = asset
            self._order_ids.append(asset.id)
            self.assets_changed.emit()

    def get_asset(self, asset_id: str) -> Optional[WorkspaceAsset]:
        """IDからアセットを取得する。"""
        return self._assets_dict.get(asset_id)

    def all_assets(self) -> List[WorkspaceAsset]:
        """棚にある全アセットを表示順通りにリストで取得。"""
        return [self._assets_dict[aid] for aid in self._order_ids]

    def move_asset(self, old_idx: int, new_idx: int):
        """アセットの表示順序を入れ替える。"""
        if 0 <= old_idx < len(self._order_ids) and 0 <= new_idx < len(self._order_ids):
            asset_id = self._order_ids.pop(old_idx)
            self._order_ids.insert(new_idx, asset_id)
            self.assets_changed.emit()

    def toggle_visibility(self, asset_id: str):
        """アセットの表示/非表示を切り替える。"""
        asset = self.get_asset(asset_id)
        if asset:
            asset.is_visible = not asset.is_visible
            self.assets_changed.emit()

    def to_snapshot(self) -> dict:
        """全アセットと表示順を辞書形式（スナップショット）に変換"""
        return {
            "order": self._order_ids,
            "assets": {
                aid: asset.to_dict() for aid, asset in self._assets_dict.items()
            },
        }

    def load_snapshot(self, data: dict):
        """スナップショットからアセット群を再構築する"""
        self._assets_dict.clear()
        self._order_ids = data.get("order", [])

        asset_data_map = data.get("assets", {})
        class_map = {
            "SourceAsset": SourceAsset,
            "CroppedAsset": CroppedAsset,
            "JoinedAsset": JoinedAsset,
        }

        for aid, a_info in asset_data_map.items():
            cls_name = a_info.get("type")
            if cls_name in class_map:
                asset = class_map[cls_name].from_dict(a_info)
                self._assets_dict[aid] = asset

        self.assets_changed.emit()

    def create_source(self, file_path: str):
        """外部ファイルから生の素材アセットを生成・登録する。"""
        import os

        name = os.path.basename(file_path)
        asset = SourceAsset(name, file_path)
        self.register_asset(asset)
        return asset

    def create_cropped(
        self,
        parent_id: str,
        crop_rects: List[QRectF],
        scale_factor: float,
        name: str = None,
    ):
        """既存のアセットを切り抜いた中間生成物を生成・登録する。"""
        if not name:
            name = f"part_{str(uuid.uuid4())[:4]}"
        asset = CroppedAsset(name, parent_id, crop_rects, scale_factor)
        self.register_asset(asset)
        return asset

    def create_joined(self, item_ids: List[str], name: str = None):
        if not name:
            name = "Project_" + str(uuid.uuid4())[:4]
        asset = JoinedAsset(name, item_ids)
        self.register_asset(asset)
        return asset
