import fitz
from PySide6.QtGui import QImage, QPixmap
from pdf_metadata import normalize_pdf_rotation_to_bytes


class PdfPageTransformer:
    """
    PDFページの座標系（生データ ⇔ 視覚的表示）を変換する。
    Rotation（回転）設定を反映し、視覚的な位置と内部座標を相互にマッピングする。
    ※ transformation_matrix と異なり UserUnit を含まないため、外部のスケール管理と共存できる。
    """

    def __init__(self, page):
        # rotation_matrix は、MediaBox(生座標)を視覚的な配置(page.rect)へ変換する行列
        self.matrix = page.rotation_matrix
        self.inv_matrix = ~self.matrix

    def to_visual(self, rect):
        """PDF内部の生座標を、UI表示用の視覚座標（回転反映済み）に変換"""
        if rect is None:
            return None
        return rect * self.matrix

    def to_source(self, rect):
        """UIの指定（視覚座標）を、PDF内部の生座標に戻す"""
        if rect is None:
            return None
        return rect * self.inv_matrix


class PdfProcessor:
    """PDFの操作に関するすべてのロジックをカプセル化するクラス"""

    IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff")

    @staticmethod
    def get_page_image(pdf_path: str, page_index: int = 0, dpi: int = 216) -> tuple:
        """指定したPDFページを高画質で画像化して返す (標準72dpiに対して216dpi = 3倍画質)"""
        with PdfProcessor._open_as_pdf(pdf_path) as doc:
            page = doc[page_index]

            # DPI指定で画像化
            pix = page.get_pixmap(dpi=dpi)

            # PyMuPDFのデータからQPixmapを生成
            img_data = pix.tobytes("png")
            image = QImage.fromData(img_data)
            pixmap = QPixmap.fromImage(image)

            # 視覚的な幅（回転適用後）を返す。
            # page.rect は transformation_matrix 適用済みのサイズを返す。
            original_width = page.rect.width

            # 画像と、後で座標変換に使う「元の幅」を返す
            return pixmap, original_width

    @staticmethod
    def detect_frames(pdf_path: str, page_index: int = 0) -> list:
        """
        PDF内のベクターデータを解析して矩形枠を検知する
        ページに回転設定がある場合、座標変換を行って視覚的な位置に補正する
        """
        detected_rects = []
        try:
            with PdfProcessor._open_as_pdf(pdf_path) as doc:
                page = doc[page_index]
                page_rect = page.rect
                trans = PdfPageTransformer(page)

                # ページ上の全ての描画オブジェクトを取得
                drawings = page.get_drawings()

                for d in drawings:
                    # 視覚的な座標（表示上の向き）に変換
                    r = trans.to_visual(d["rect"])

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
        """指定パスを開き、必要に応じて画像変換や回転正規化を行って返す（with構文対応）"""
        doc = fitz.open(path)
        if not doc.is_pdf:
            with doc:
                return fitz.open("pdf", doc.convert_to_pdf())

        # PDFは pypdf で回転正規化を試みる
        doc.close()
        normalized_bytes = normalize_pdf_rotation_to_bytes(path)
        if normalized_bytes is not None:
            return fitz.open("pdf", normalized_bytes)

        return fitz.open(path)

    @staticmethod
    def crop_and_save(
        input_path: str,
        output_path: str,
        crop_rects: list,
        scale_factor: float,
        progress_callback=None,
        is_cancelled_cb=None,
    ):
        """
        クロップ処理を行い、新しいPDFとして保存する
        crop_rects: [(left, top, right, bottom), ...] のような数値タプルのリスト
        """
        with PdfProcessor._open_as_pdf(input_path) as src_doc:
            total_pages = len(src_doc)
            total_crops = len(crop_rects)
            total_steps = total_pages * total_crops
            current_step = 0

            # 基準となる横幅（最初のページの幅）を取得
            target_width = src_doc[0].rect.width if total_pages > 0 else None

            with fitz.open() as new_doc:
                for page_index in range(total_pages):
                    for rect in crop_rects:
                        # 中断チェック
                        if is_cancelled_cb and is_cancelled_cb():
                            return False

                        PdfProcessor._append_cropped_page(
                            new_doc,
                            src_doc,
                            page_index,
                            rect,
                            scale_factor,
                            target_width=target_width,
                        )
                        current_step += 1
                        if progress_callback:
                            progress_callback(current_step, total_steps)

                new_doc.set_page_labels([])
                try:
                    root_xref = new_doc.pdf_catalog()
                    # 表示レイアウトを「SinglePage（1枚ずつ）」に固定
                    new_doc.xref_set_key(root_xref, "PageLayout", "/SinglePage")
                    new_doc.xref_set_key(root_xref, "PageMode", "/UseNone")
                    new_doc.xref_set_key(
                        root_xref, "ViewerPreferences", "<< /Direction /L2R >>"
                    )
                except Exception as e:
                    print(f"Metadata cleanup warning: {e}")
                new_doc.init_doc()
                new_doc.save(output_path, garbage=4, deflate=True, clean=True)
        return True

    @staticmethod
    def generate_page_preview(
        pdf_path: str,
        page_index: int,
        crop_coords: list,
        scale_factor: float,
        preview_dpi: int = 144,
    ):
        """特定のページのみのプレビュー画像リストを返す"""
        with PdfProcessor._open_as_pdf(pdf_path) as doc:
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
        target_width: float = None,
    ):
        """
        [内部専用] 元のドキュメントの指定ページを新しいドキュメントの末尾に追加し、切り抜き枠を適用する
        """
        src_page = src_doc[page_index]
        trans = PdfPageTransformer(src_page)

        # UIの視覚座標（ポイント単位にスケール済み）
        left, top, right, bottom = rect
        visual_rect = fitz.Rect(
            left * scale_factor,
            top * scale_factor,
            right * scale_factor,
            bottom * scale_factor,
        )

        # 視覚座標をPDF内部の生座標（ソース座標）に変換
        pdf_rect = trans.to_source(visual_rect)

        # 1. 完全にクリーンな(0, 0)始まりの新しいページを作成する
        # target_width が指定されている場合はそれに合わせ、指定がない場合は視覚的な切り抜きサイズに合わせる
        if target_width:
            aspect_ratio = visual_rect.height / visual_rect.width
            w, h = target_width, target_width * aspect_ratio
        else:
            w, h = visual_rect.width, visual_rect.height

        new_page = new_doc.new_page(width=w, height=h)

        # 2. 元のPDFの該当ページから、変換した座標(pdf_rect)を抽出して新しいページへ転写
        # show_pdf_page は、ソースページの rotation 属性を見て自動的に回転を考慮して転写してくれる
        new_page.show_pdf_page(
            new_page.rect,  # 転写先（新ページの0,0から幅・高さまで）
            src_doc,  # 転送元ドキュメント
            page_index,  # 転送元ページ番号
            clip=pdf_rect,  # 転送元から切り出す範囲（ソース座標）
        )

    @staticmethod
    def _append_width_matched_pdf_page(
        new_doc: fitz.Document,
        src_doc: fitz.Document,
        page_index: int,
        target_width: float,
    ):
        """
        [内部専用] 指定したPDFページを、アスペクト比を維持しつつ指定の横幅にスケーリングして追加する
        """
        src_page = src_doc[page_index]
        # src_page.rect は回転適用済みの視覚的な矩形
        aspect_ratio = src_page.rect.height / src_page.rect.width
        target_height = target_width * aspect_ratio

        new_page = new_doc.new_page(width=target_width, height=target_height)
        # show_pdf_page は new_page.rect に合わせて自動でスケーリングされる
        new_page.show_pdf_page(new_page.rect, src_doc, page_index)

    @staticmethod
    def _get_cached_doc(path: str, cache: dict[str, fitz.Document]) -> fitz.Document:
        """キャッシュからドキュメントを取得、なければ開いてキャッシュに登録する内部関数"""
        if path not in cache:
            cache[path] = PdfProcessor._open_as_pdf(path)
        return cache[path]

    @staticmethod
    def _resolve_target_width_from_assets(
        assets_metadata: list,
        fallback_width: float = 595.0,
        doc_cache: dict[str, fitz.Document] = None,
    ) -> float:
        """
        結合候補から最初に見つかるPDFページ幅を返す。
        見つからない場合は fallback_width を返す。
        """
        for meta in assets_metadata:
            path = meta.get("path")
            if not path:
                continue
            try:
                if doc_cache is not None:
                    src_raw = PdfProcessor._get_cached_doc(path, doc_cache)
                    if src_raw.is_pdf and len(src_raw) > 0:
                        return float(src_raw[0].rect.width)
                else:
                    with PdfProcessor._open_as_pdf(path) as src_raw:
                        if src_raw.is_pdf and len(src_raw) > 0:
                            return float(src_raw[0].rect.width)
            except Exception:
                continue
        return fallback_width

    @staticmethod
    def _resolve_target_width_from_instructions(
        instructions: list[dict],
        fallback_width: float = 595.0,
        doc_cache: dict[str, fitz.Document] = None,
    ) -> float:
        """
        Organizeの指示から最初に見つかるPDFページ幅を返す。
        見つからない場合は fallback_width を返す。
        """
        for item in instructions:
            if item.get("excluded", False):
                continue
            if item.get("type") != "pdf_page":
                continue

            src_path = item.get("source_path")
            page_idx = item.get("page_index", 0)
            if not src_path:
                continue

            try:
                if doc_cache is not None:
                    src_raw = PdfProcessor._get_cached_doc(src_path, doc_cache)
                    if src_raw.is_pdf and 0 <= page_idx < len(src_raw):
                        return float(src_raw[page_idx].rect.width)
                else:
                    with PdfProcessor._open_as_pdf(src_path) as src_raw:
                        if src_raw.is_pdf and 0 <= page_idx < len(src_raw):
                            return float(src_raw[page_idx].rect.width)
            except Exception:
                continue
        return fallback_width

    @staticmethod
    def _append_image_as_width_matched_page(
        new_doc: fitz.Document, image_path: str, target_width: float
    ) -> None:
        """
        画像を target_width に合わせた新規ページとして挿入する。
        高さはアスペクト比を維持して算出する。
        """
        image = QImage(image_path)
        if image.isNull():
            raise ValueError(f"Failed to load image: {image_path}")

        img_w = float(image.width())
        img_h = float(image.height())
        if img_w <= 0 or img_h <= 0:
            raise ValueError(f"Invalid image size: {image_path}")

        target_h = target_width * (img_h / img_w)
        page = new_doc.new_page(width=target_width, height=target_h)
        page.insert_image(page.rect, filename=image_path, keep_proportion=True)

    @staticmethod
    def join_and_save(
        output_path: str,
        assets_metadata: list,
        progress_callback=None,
        is_cancelled_cb=None,
    ):
        """
        リスト上の全アセットを一本の物理PDFとして結合保存する。
        assets_metadata: [
            {"path": str, "crop_coords": [(l,t,r,b), ...], "scale_factor": float},
            ...
        ]
        """
        total_items = len(assets_metadata)
        current_item = 0
        doc_cache: dict[str, fitz.Document] = {}

        try:
            with fitz.open() as new_doc:
                target_width = PdfProcessor._resolve_target_width_from_assets(
                    assets_metadata, doc_cache=doc_cache
                )
                for meta in assets_metadata:
                    # 中断チェック
                    if is_cancelled_cb and is_cancelled_cb():
                        return False

                    path = meta["path"]
                    crop_coords = meta["crop_coords"]
                    scale_factor = meta["scale_factor"]

                    try:
                        is_image_file = path.lower().endswith(
                            PdfProcessor.IMAGE_EXTENSIONS
                        )
                        if not is_image_file:
                            # PDFは基準の横幅に合わせてスケーリングして挿入
                            src_doc = PdfProcessor._get_cached_doc(path, doc_cache)
                            if not crop_coords:
                                for p_idx in range(len(src_doc)):
                                    PdfProcessor._append_width_matched_pdf_page(
                                        new_doc, src_doc, p_idx, target_width
                                    )
                            else:
                                # 切り抜き処理
                                for page_index in range(len(src_doc)):
                                    for rect in crop_coords:
                                        PdfProcessor._append_cropped_page(
                                            new_doc,
                                            src_doc,
                                            page_index,
                                            rect,
                                            scale_factor,
                                            target_width=target_width,
                                        )
                        else:
                            # 画像は幅を基準PDFに合わせて1ページ化
                            if not crop_coords:
                                PdfProcessor._append_image_as_width_matched_page(
                                    new_doc, path, target_width
                                )
                            else:
                                # 画像の切り抜き（必要であれば実装）
                                pass
                    except Exception as e:
                        print(f"Error merging {path}: {e}")

                    current_item += 1
                    if progress_callback:
                        progress_callback(current_item, total_items)

                # 最終的なPDFを物理ファイルに書き出す
                new_doc.save(output_path)
            return True
        finally:
            # キャッシュしたドキュメントをすべて閉じる
            for doc in doc_cache.values():
                doc.close()

    @staticmethod
    def export_organized_pdf(
        instructions: list[dict],
        output_path: str,
        progress_callback=None,
        is_cancelled_cb=None,
    ):
        """
        OrganizeDeskWidgetのリスト順序・除外フラグに基づき、PDFを構築・保存する。
        """
        total_items = len(instructions)
        current_item = 0
        doc_cache: dict[str, fitz.Document] = {}

        try:
            with fitz.open() as new_doc:
                target_width = PdfProcessor._resolve_target_width_from_instructions(
                    instructions, doc_cache=doc_cache
                )
                i = 0
                while i < total_items:
                    # 中断チェック
                    if is_cancelled_cb and is_cancelled_cb():
                        return False

                    item = instructions[i]

                    # 除外フラグが立っている場合はスキップ
                    if item.get("excluded", False):
                        current_item += 1
                        i += 1
                        if progress_callback:
                            progress_callback(current_item, total_items)
                        continue

                    src_path = item["source_path"]
                    item_type = item["type"]

                    try:
                        if item_type == "pdf_page":
                            src_doc = PdfProcessor._get_cached_doc(src_path, doc_cache)
                            start_page_idx = item["page_index"]

                            # 高速コピー（insert_pdf）が可能な範囲（ラン）を特定する
                            run_end_i = i - 1
                            if (
                                abs(src_doc[start_page_idx].rect.width - target_width)
                                < 0.1
                            ):
                                run_end_i = i
                                while run_end_i + 1 < total_items:
                                    next_item = instructions[run_end_i + 1]
                                    if (
                                        not next_item.get("excluded")
                                        and next_item.get("type") == "pdf_page"
                                        and next_item.get("source_path") == src_path
                                        and next_item.get("page_index")
                                        == instructions[run_end_i]["page_index"] + 1
                                        and abs(
                                            src_doc[next_item["page_index"]].rect.width
                                            - target_width
                                        )
                                        < 0.1
                                    ):
                                        run_end_i += 1
                                    else:
                                        break

                            if run_end_i >= i:
                                # 一括挿入（またはリサイズ不要な単一ページ挿入）
                                num_processed = (run_end_i - i) + 1
                                end_page_idx = instructions[run_end_i]["page_index"]
                                new_doc.insert_pdf(
                                    src_doc,
                                    from_page=start_page_idx,
                                    to_page=end_page_idx,
                                )
                            else:
                                # 個別挿入（リサイズあり）
                                num_processed = 1
                                PdfProcessor._append_width_matched_pdf_page(
                                    new_doc, src_doc, start_page_idx, target_width
                                )

                            # 共通の進捗更新とインデックス加算
                            current_item += num_processed
                            if progress_callback:
                                progress_callback(current_item, total_items)
                            i += num_processed

                        elif item_type == "image_file":
                            PdfProcessor._append_image_as_width_matched_page(
                                new_doc, src_path, target_width
                            )
                            current_item += 1
                            if progress_callback:
                                progress_callback(current_item, total_items)
                            i += 1
                    except Exception as e:
                        print(f"Error exporting item {src_path}: {e}")
                        raise e

                # 最終的なPDFを物理ファイルに書き出す
                new_doc.save(output_path)
            return True
        finally:
            # キャッシュしたドキュメントをすべて閉じる
            for doc in doc_cache.values():
                doc.close()
