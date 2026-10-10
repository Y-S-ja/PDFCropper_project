import copy
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, List, Tuple
from PySide6.QtCore import QPointF, QRectF


class CopyScope(Enum):
    ALL = auto()          # 全ページ
    FORWARD = auto()      # 現在ページ以降
    ODD_PAGES = auto()    # 奇数ページのみ (1, 3, 5, ...)
    EVEN_PAGES = auto()   # 偶数ページのみ (2, 4, 6, ...)
    CUSTOM = auto()       # 指定範囲


class ConflictPolicy(Enum):
    OVERWRITE = auto()    # 上書き（既存枠を削除して置換）
    APPEND = auto()       # 追加（既存枠を残して末尾に追加）
    SKIP = auto()         # 既存枠があるページはスキップ


class FitPolicy(Enum):
    PROPORTIONAL = auto()  # ページサイズの比率に合わせて自動伸縮（推奨デフォルト）
    ORIGINAL = auto()      # 元の絶対サイズを維持


@dataclass
class PageCopyOptions:
    """枠コピーの詳細設定を保持するデータクラス"""
    scope: CopyScope = CopyScope.ALL
    conflict: ConflictPolicy = ConflictPolicy.OVERWRITE
    fit_policy: FitPolicy = FitPolicy.PROPORTIONAL
    custom_pages: Optional[List[int]] = None
    mirror_horizontal: bool = False  # 将来の見開きミラー反転用


class PageCopyEngine:
    """枠コピーの対象ページ解決および適用ロジックを担当するエンジン"""

    @staticmethod
    def resolve_target_pages(
        current_page: int, total_pages: int, options: PageCopyOptions
    ) -> List[int]:
        """設定に基づいてコピー先となるページ番号リスト（0-indexed）を算出する"""
        if total_pages <= 0:
            return []

        if options.scope == CopyScope.ALL:
            pages = list(range(total_pages))
        elif options.scope == CopyScope.FORWARD:
            pages = list(range(current_page, total_pages))
        elif options.scope == CopyScope.ODD_PAGES:
            # 1-indexedでの奇数ページ (インデックス 0, 2, 4, ...)
            pages = [p for p in range(total_pages) if (p + 1) % 2 != 0]
        elif options.scope == CopyScope.EVEN_PAGES:
            # 1-indexedでの偶数ページ (インデックス 1, 3, 5, ...)
            pages = [p for p in range(total_pages) if (p + 1) % 2 == 0]
        elif options.scope == CopyScope.CUSTOM and options.custom_pages:
            pages = [p for p in options.custom_pages if 0 <= p < total_pages]
        else:
            pages = []

        # コピー元（現在ページ自身）は除外
        return [p for p in pages if p != current_page]

    @staticmethod
    def transform_snapshot(
        snapshot: list,
        src_size: Tuple[float, float],
        dst_size: Tuple[float, float],
        fit_policy: FitPolicy = FitPolicy.PROPORTIONAL,
    ) -> list:
        """
        元ページの枠スナップショットをコピー先ページの寸法に合わせて変換する。
        src_size: (width, height)
        dst_size: (width, height)
        """
        if not snapshot:
            return []

        src_w, src_h = src_size
        dst_w, dst_h = dst_size

        # サイズが同一、またはORIGINAL指定の場合はディープコピーをそのまま返す
        if fit_policy == FitPolicy.ORIGINAL or (src_w == dst_w and src_h == dst_h):
            return copy.deepcopy(snapshot)

        if src_w <= 0 or src_h <= 0 or dst_w <= 0 or dst_h <= 0:
            return copy.deepcopy(snapshot)

        scale_x = dst_w / src_w
        scale_y = dst_h / src_h

        transformed = []
        for pos, rect, rect_id, group_id, quadrant_id in snapshot:
            new_pos = QPointF(pos.x() * scale_x, pos.y() * scale_y)
            new_rect = QRectF(
                rect.x() * scale_x,
                rect.y() * scale_y,
                rect.width() * scale_x,
                rect.height() * scale_y,
            )
            transformed.append((new_pos, new_rect, rect_id, group_id, quadrant_id))

        return transformed
