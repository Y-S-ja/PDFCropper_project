import fitz
from PySide6.QtGui import QImage, QPixmap


class PdfProcessor:
    """PDFの操作に関するすべてのロジックをカプセル化するクラス"""

    @staticmethod
    def get_page_image(pdf_path: str, page_index: int = 0, dpi: int = 216) -> tuple:
        """指定したPDFページを高画質で画像化して返す (標準72dpiに対して216dpi = 3倍画質)"""
        with fitz.open(pdf_path) as doc:
            page = doc[page_index]

            # DPI指定で画像化
            pix = page.get_pixmap(dpi=dpi)

            # PyMuPDFのデータからQPixmapを生成
            img_data = pix.tobytes("png")
            image = QImage.fromData(img_data)
            pixmap = QPixmap.fromImage(image)

            original_width = page.rect.width

            # 画像と、後で座標変換に使う「元の幅」を返す
            return pixmap, original_width

    @staticmethod
    def detect_frames(pdf_path: str, page_index: int = 0) -> list:
        """
        PDF内のベクターデータを解析して矩形枠を検知する (方針1)
        """
        detected_rects = []
        try:
            with fitz.open(pdf_path) as doc:
                page = doc[page_index]
                page_rect = page.rect
                # ページ上の全ての描画オブジェクトを取得
                drawings = page.get_drawings()

                for d in drawings:
                    r = d["rect"]

                    # 1. フィルタリング：ページの端に近すぎる全体枠（外枠）は除外
                    if (
                        r.width > page_rect.width * 0.98
                        and r.height > page_rect.height * 0.98
                    ):
                        continue

                    # 2. フィルタリング：小さすぎるゴミ（10pt以下）は除外
                    if r.width < 10 or r.height < 10:
                        continue

                    # 3. 重複排除：ほぼ同じ位置にある枠は1つにまとめる
                    is_duplicate = False
                    for existing in detected_rects:
                        if (
                            abs(existing.x0 - r.x0) < 2
                            and abs(existing.y0 - r.y0) < 2
                            and abs(existing.x1 - r.x1) < 2
                            and abs(existing.y1 - r.y1) < 2
                        ):
                            is_duplicate = True
                            break

                    if not is_duplicate:
                        detected_rects.append(r)

            # (left, top, right, bottom) の形式で返す
            return [(r.x0, r.y0, r.x1, r.y1) for r in detected_rects]

        except Exception as e:
            print(f"Error detecting frames: {e}")
            return []

    @staticmethod
    def _open_as_pdf(path: str) -> fitz.Document:
        """指定パスのファイルを開き、画像の場合はメモリ上でPDFに変換して返す（with構文対応）"""
        doc = fitz.open(path)
        if not doc.is_pdf:
            pdf_bytes = doc.convert_to_pdf()
            doc.close()
            return fitz.open("pdf", pdf_bytes)
        return doc

    @staticmethod
    def crop_and_save(
        input_path: str, output_path: str, crop_rects: list, scale_factor: float
    ):
        """
        クロップ処理を行い、新しいPDFとして保存する
        crop_rects: [(left, top, right, bottom), ...] のような数値タプルのリスト
        """
        with PdfProcessor._open_as_pdf(input_path) as src_doc:
            with fitz.open() as new_doc:
                for page_index in range(len(src_doc)):
                    for rect in crop_rects:
                        PdfProcessor._append_cropped_page(
                            new_doc, src_doc, page_index, rect, scale_factor
                        )
                new_doc.set_page_labels([])
                try:
                    root_xref = new_doc.pdf_catalog()
                    # 表示レイアウトを「SinglePage（1枚ずつ）」に固定
                    # これによりObsidianが偶数ページを隣とくっつけるのを防ぎます
                    new_doc.xref_set_key(root_xref, "PageLayout", "/SinglePage")
                    new_doc.xref_set_key(root_xref, "PageMode", "/UseNone")

                    # さらに、ビューアへの詳細な指示を追加
                    # /Direction /L2R (左から右へ読む) を明示
                    new_doc.xref_set_key(
                        root_xref, "ViewerPreferences", "<< /Direction /L2R >>"
                    )
                except Exception as e:
                    print(f"Metadata cleanup warning: {e}")
                new_doc.init_doc()
                new_doc.save(output_path, garbage=4, deflate=True, clean=True)

    @staticmethod
    def generate_page_preview(
        pdf_path: str,
        page_index: int,
        crop_coords: list,
        scale_factor: float,
        preview_dpi: int = 144,
    ):
        """特定のページのみのプレビュー画像リストを返す"""
        with fitz.open(pdf_path) as doc:
            return PdfProcessor._get_previews_for_page(
                doc, page_index, crop_coords, scale_factor, preview_dpi
            )

    @staticmethod
    def _get_previews_for_page(doc, page_index, crop_coords, scale_factor, preview_dpi):
        """1ページ分のプレビュー画像を抽出する内部関数"""
        page = doc[page_index]
        page_rect = page.rect
        page_images = []

        for rect in crop_coords:
            left, top, right, bottom = rect

            # シーン座標をPDFのポイント座標に変換
            fitz_rect = fitz.Rect(
                left * scale_factor,
                top * scale_factor,
                right * scale_factor,
                bottom * scale_factor,
            )

            # ページ範囲内にクランプ（はみ出し防止）
            fitz_rect.intersect(page_rect)

            if fitz_rect.is_empty or fitz_rect.width < 1 or fitz_rect.height < 1:
                page_images.append(None)
                continue

            try:
                pix = page.get_pixmap(clip=fitz_rect, dpi=preview_dpi)
                img = QImage(
                    pix.samples,
                    pix.width,
                    pix.height,
                    pix.stride,
                    QImage.Format_RGB888,
                ).copy()
                page_images.append(img)
            except Exception:
                page_images.append(None)

        return page_images

    @staticmethod
    def _append_cropped_page(
        new_doc: fitz.Document,
        src_doc: fitz.Document,
        page_index: int,
        rect: tuple,
        scale_factor: float,
    ):
        """
        [内部専用] 元のドキュメントの指定ページを新しいドキュメントの末尾に追加し、切り抜き枠を適用する
        """
        # UIの数値(タプル)を受け取り、シーン座標をPDFのポイント座標に変換
        left, top, right, bottom = rect
        pdf_rect = fitz.Rect(
            left * scale_factor,
            top * scale_factor,
            right * scale_factor,
            bottom * scale_factor,
        )

        # 1. 完全にクリーンな(0, 0)始まりの新しいページを作成する
        # （これによりPDF++等の「左上が基準」の座標抽出ツールが正しく動作し、左右の配置順序の逆転も防ぐ）
        new_page = new_doc.new_page(width=pdf_rect.width, height=pdf_rect.height)

        # 2. 元のPDFの該当ページから、切り抜き枠の部分だけを新しいページ(の全域)へ写し取る
        new_page.show_pdf_page(
            new_page.rect,  # 転写先（新ページの0,0から幅・高さまで）
            src_doc,  # 転送元ドキュメント
            page_index,  # 転送元ページ番号
            clip=pdf_rect,  # 転送元から切り出す範囲
        )

    @staticmethod
    def join_and_save(output_path: str, assets_metadata: list):
        """
        リスト上の全アセットを一本の物理PDFとして結合保存する。
        assets_metadata: [
            {"path": str, "crop_coords": [(l,t,r,b), ...], "scale_factor": float},
            ...
        ]
        """
        with fitz.open() as new_doc:
            for meta in assets_metadata:
                path = meta["path"]
                crop_coords = meta["crop_coords"]
                scale_factor = meta["scale_factor"]

                try:
                    with PdfProcessor._open_as_pdf(path) as src_doc:
                        if not crop_coords:
                            # 1. 生ファイルの場合は全ページをそのまま挿入
                            new_doc.insert_pdf(src_doc)
                        else:
                            # 2. 切り抜きパーツの場合は専門関数を使って1ページずつ処理して挿入
                            for page_index in range(len(src_doc)):
                                for rect in crop_coords:
                                    PdfProcessor._append_cropped_page(
                                        new_doc, src_doc, page_index, rect, scale_factor
                                    )
                except Exception as e:
                    print(f"Error merging {path}: {e}")

            # 最終的なPDFを物理ファイルに書き出す
            new_doc.save(output_path)
