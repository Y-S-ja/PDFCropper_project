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
    def crop_and_save(
        input_path: str, output_path: str, crop_rects: list, scale_factor: float
    ):
        """
        クロップ処理を行い、新しいPDFとして保存する
        crop_rects: [(left, top, right, bottom), ...] のような数値タプルのリスト
        """
        with fitz.open(input_path) as src_doc:
            with fitz.open() as new_doc:
                for page_index in range(len(src_doc)):
                    for rect in crop_rects:
                        new_doc.insert_pdf(
                            src_doc, from_page=page_index, to_page=page_index
                        )

                        # UIのオブジェクト(QRectF等)ではなく、ただの数値(タプル)として受け取る
                        left, top, right, bottom = rect

                        # シーン座標をPDFのピクセル座標に変換
                        pdf_rect = fitz.Rect(
                            left * scale_factor,
                            top * scale_factor,
                            right * scale_factor,
                            bottom * scale_factor,
                        )
                        new_doc[-1].set_cropbox(pdf_rect)

                new_doc.save(output_path)

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
                    with fitz.open(path) as src_doc:
                        if not crop_coords:
                            # 1. 生ファイルの場合は全ページをそのまま挿入
                            new_doc.insert_pdf(src_doc)
                        else:
                            # 2. 切り抜きパーツの場合は全ページにレシピを適用して挿入
                            for page_index in range(len(src_doc)):
                                for rect in crop_coords:
                                    # 原本の1ページを新しいドキュメントの末尾に追加
                                    new_doc.insert_pdf(
                                        src_doc, from_page=page_index, to_page=page_index
                                    )
                                    
                                    # 追加したページに切り抜き枠を適用
                                    left, top, right, bottom = rect
                                    pdf_rect = fitz.Rect(
                                        left * scale_factor,
                                        top * scale_factor,
                                        right * scale_factor,
                                        bottom * scale_factor,
                                    )
                                    new_doc[-1].set_cropbox(pdf_rect)
                                    
                except Exception as e:
                    print(f"Error merging {path}: {e}")

            # 最終的なPDFを物理ファイルに書き出す
            new_doc.save(output_path)
