import tkinter as tk
from tkinter import messagebox, filedialog
from PIL import Image, ImageTk
import fitz
from pypdf import PdfReader, PdfWriter
import ctypes

# DPI設定（クッキリ）
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except:
    pass

class ZoomablePdfCropperApp:
    def __init__(self, root, pdf_path):
        self.root = root
        self.root.title("ズーム対応PDFカッター")
        self.pdf_path = pdf_path

        # --- 1. 画像の準備 ---
        self.doc = fitz.open(pdf_path)
        # かなり高画質で読み込んでおく（ズーム耐性のため）
        zoom_extract = 3.0 
        pix = self.doc[0].get_pixmap(matrix=fitz.Matrix(zoom_extract, zoom_extract))
        
        # 「原本」として保持しておく（ここから毎回リサイズする）
        self.original_image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        # 現在の表示用画像
        self.current_scale = 1.0 # 初期の縮小率（後で計算）
        self.displayed_image = None
        
        # 初期表示サイズ（高さ600pxに合わせる）
        target_height = 600
        self.current_scale = target_height / self.original_image.height
        
        # --- 2. GUI配置（スクロールバー対応） ---
        self.toolbar = tk.Frame(root)
        self.toolbar.pack(side="top", fill="x", padx=10, pady=5)

        # ボタン類
        tk.Button(self.toolbar, text="保存", command=self.save_all_clips, bg="lightblue").pack(side="left", padx=5)
        tk.Button(self.toolbar, text="全消去", command=self.clear_rects).pack(side="left", padx=5)
        
        # ズームボタンを追加
        tk.Button(self.toolbar, text="＋ 拡大", command=lambda: self.zoom(1.2)).pack(side="left", padx=10)
        tk.Button(self.toolbar, text="－ 縮小", command=lambda: self.zoom(0.8)).pack(side="left", padx=5)

        # --- キャンバスとスクロールバーをまとめるフレーム ---
        self.canvas_frame = tk.Frame(root)
        self.canvas_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # 縦スクロールバー
        self.v_scroll = tk.Scrollbar(self.canvas_frame, orient="vertical")
        self.v_scroll.pack(side="right", fill="y")

        # 横スクロールバー
        self.h_scroll = tk.Scrollbar(self.canvas_frame, orient="horizontal")
        self.h_scroll.pack(side="bottom", fill="x")

        # キャンバス作成
        self.canvas = tk.Canvas(self.canvas_frame, bg="gray", cursor="cross",
                                xscrollcommand=self.h_scroll.set,
                                yscrollcommand=self.v_scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)

        # スクロールバーとキャンバスを紐付け
        self.v_scroll.config(command=self.canvas.yview)
        self.h_scroll.config(command=self.canvas.xview)

        # 初期画像の描画
        self.update_image_display()

        # 状態管理
        # リストはこれ1本にする！
        self.crop_areas = []
        self.start_x = 0
        self.start_y = 0

        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_move)
        self.canvas.bind("<Button-3>", self.on_right_click)

    def update_image_display(self):
        # 原本から現在の倍率でリサイズ
        w = int(self.original_image.width * self.current_scale)
        h = int(self.original_image.height * self.current_scale)
        resized = self.original_image.resize((w, h), Image.LANCZOS)
        
        self.tk_image = ImageTk.PhotoImage(resized)

        # キャンバス上の画像を更新（ID=1 は常に画像であることを前提）
        # まだ画像がない場合は作成、あれば差し替え
        if not self.canvas.find_withtag("bg_image"):
            self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image, tags="bg_image")
        else:
            self.canvas.itemconfig("bg_image", image=self.tk_image)
        
        # スクロール範囲を画像の大きさに合わせる
        self.canvas.config(scrollregion=(0, 0, w, h))

    def zoom(self, factor):
        # 1. 画像の倍率を変更
        self.current_scale *= factor
        
        # 2. キャンバス上のすべての図形（枠と文字）を座標変換
        # scale("all", 基準x, 基準y, x倍率, y倍率)
        self.canvas.scale("all", 0, 0, factor, factor)
        
        # 3. 画像だけは画質維持のため作り直して差し替え
        self.update_image_display()

    def on_press(self, event):
        # キャンバスがスクロールしている場合、event.x は「見えている画面上の座標」になるため、
        # canvasx() を使って「キャンバス全体の絶対座標」に変換する必要がある
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        
        self.start_x, self.start_y = canvas_x, canvas_y
        
        new_rect = self.canvas.create_rectangle(
            canvas_x, canvas_y, canvas_x, canvas_y, 
            outline="red", width=2, fill="red", stipple="gray12"
        )
        
        text_id = self.canvas.create_text(
            canvas_x, canvas_y,
            text=str(len(self.rects)),
            fill="red",
            anchor="se"
        )

        new_item = {
            "rect_id":new_erct,
            "text_id":text_id
        }
        self.crop_areas.append(new_item)

    def on_move(self, event):
        # 枠を動かす
        if self.crop_areas:
            # スクロール対応座標
            cur_x = self.canvas.canvasx(event.x)
            cur_y = self.canvas.canvasy(event.y)

            x2 = max(self.start_x, cur_x)
            y2 = max(self.start_y, cur_y)
            x1 = min(self.start_x, cur_x)
            y1 = min(self.start_y, cur_y)

            current_item = self.crop_areas[-1]

            self.canvas.coords(current_item["rect_id"], x1, y1, x2, y2)
            
            # 番号を枠の右下(x2, y2)の少し内側に配置
            # anchor="se" を指定しているので、(x2, y2)が文字の右下角になります
            self.canvas.coords(current_item["text_id"], x2 - 5, y2 - 5)
    
    # 右クリックで個別削除
    def on_right_click(self, event):
        # スクロール対応座標
        click_x = self.canvas.canvasx(event.x)
        click_y = self.canvas.canvasy(event.y)
        
        closest = self.canvas.find_closest(click_x, click_y)
        if closest:
            t_id = closest[0]
        else: return

        idx = -1

        for i, area in enumerate(self.crop_areas):
            # 今見ている辞書の 'rect_id' か 'text_id' のどちらかが、
            # クリックされたID(t_id)と一致するかチェック
            if t_id == area['rect_id'] or t_id == area['text_id']:
                idx = i
                break # 見つかったのでループを抜ける

        if idx != -1:
            target_item = self.crop_areas[idx]
            self.canvas.delete(target_item['rect_id'])
            self.canvas.delete(target_item['text_id'])
            self.crop_areas.pop(target_idx)
            self.reorder_numbers()

    # 番号を振り直す
    def reorder_numbers(self):
        # crop_areasの中にある全てのtext_idを順番に書き換える
        for i, area in enumerate(self.crop_areas):
            self.canvas.itemconfig(area['text_id'], text=str(i + 1))

    def clear_rects(self):
        for item in self.rects + self.texts:
            self.canvas.delete(item)
        self.rects = []
        self.texts = []

    def save_all_clips(self):
        if not self.rects:
            messagebox.showwarning("枠を1つ以上描いてください")
            return

        save_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
        if not save_path: return

        # 重要：保存時の座標計算
        # 現在表示されている画像サイズ（self.tk_image.width()）を基準に計算すれば、
        # ズーム状態に関係なく正しい比率が得られます。
        
        pdf_w = self.doc[0].rect.width
        pdf_h = self.doc[0].rect.height
        
        # 現在の画像の大きさ
        img_w = self.tk_image.width()
        img_h = self.tk_image.height()
        
        scale_x = pdf_w / img_w
        scale_y = pdf_h / img_h

        reader = PdfReader(self.pdf_path)
        writer = PdfWriter()

        for page_in in reader.pages:
            for r_id in self.rects:
                coords = self.canvas.coords(r_id)
                px1 = min(coords[0], coords[2]) * scale_x
                px2 = max(coords[0], coords[2]) * scale_x
                # Y軸反転
                py1 = (img_h - max(coords[1], coords[3])) * scale_y
                py2 = (img_h - min(coords[1], coords[3])) * scale_y

                import copy
                new_page = copy.copy(page_in)
                new_page.mediabox.lower_left = (px1, py1)
                new_page.mediabox.upper_right = (px2, py2)
                writer.add_page(new_page)

        with open(save_path, "wb") as f:
            writer.write(f)
        
        messagebox.showinfo("完了", "分割保存が完了しました！")

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
    if path:
        root.deiconify()
        app = ZoomablePdfCropperApp(root, path)
        root.mainloop()
    else:
        root.destroy()