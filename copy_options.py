import copy
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, List


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


@dataclass
class PageCopyOptions:
    """枠コピーの詳細設定を保持するデータクラス"""
    scope: CopyScope = CopyScope.ALL
    conflict: ConflictPolicy = ConflictPolicy.OVERWRITE
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
