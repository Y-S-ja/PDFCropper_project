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

class NumberedPdfCropperApp:
    def __init__(self, root, pdf_path):
        self.root = root
        self.root.title("番号付きPDFカッター")
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
        self.rects = [] # 枠のIDリスト
        self.texts = [] # 番号のIDリスト
        self.start_x = 0
        self.start_y = 0

        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_move)
        self.canvas.bind("<Button-3>", self.on_right_click)

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        
        # 1. 枠を作る
        new_rect = self.canvas.create_rectangle(self.start_x, self.start_y, event.x, event.y, outline="red", fill="red", stipple="gray12", width=2)
        self.rects.append(new_rect)
        
        # 2. 番号を作る
        text_id = self.canvas.create_text(
            self.start_x, self.start_y,
            text=str(len(self.rects)), # リストの長さを番号にする
            fill="red", # 文字色
            font=("Arial", 12, "bold"), # フォント
            anchor="se" # テキストの「南東(右下)」を基準点にする
        )
        self.texts.append(text_id)

    def on_move(self, event):
        # 枠を動かす
        if self.rects:
            # 現在の枠の範囲を決定
            # 開始点と現在点の「大きい方」が常に右下(max)になる
            x2 = max(self.start_x, event.x)
            y2 = max(self.start_y, event.y)
            x1 = min(self.start_x, event.x)
            y1 = min(self.start_y, event.y)

            self.canvas.coords(self.rects[-1], x1, y1, x2, y2)
            
            # 番号を枠の右下(x2, y2)の少し内側に配置
            # anchor="se" を指定しているので、(x2, y2)が文字の右下角になります
            self.canvas.coords(self.texts[-1], x2 - 5, y2 - 5)
    
    # 右クリックで個別削除
    def on_right_click(self, event):
        # 1. クリックされた地点のすぐ近くにあるアイテムを探す
        # find_closest は一番近いオブジェクトのIDを返します
        closest_items = self.canvas.find_closest(event.x, event.y)
        if not closest_items:
            return
        
        target_id = closest_items[0]

        # 2. そのアイテムが「枠」か「番号」のどちらに属するか調べる
        target_idx = -1
        if target_id in self.rects:
            target_idx = self.rects.index(target_id)
        elif target_id in self.texts:
            target_idx = self.texts.index(target_id)

        # 3. リストに含まれるアイテムだったら削除処理を実行
        if target_idx != -1: # アイテムが選択されていれば、target_idxは0以上
            # キャンバスから削除
            self.canvas.delete(self.rects[target_idx])
            self.canvas.delete(self.texts[target_idx])
            
            # リストから削除
            self.rects.pop(target_idx)
            self.texts.pop(target_idx)

            # 4. 番号を振り直す
            self.reorder_numbers()

    # 番号を振り直す
    def reorder_numbers(self):
        # 残っている全てのテキストの内容を「1, 2, 3...」と更新する
        for i, text_id in enumerate(self.texts):
            self.canvas.itemconfig(text_id, text=str(i + 1))

    def clear_rects(self):
        # 枠と番号を両方消す
        for r in self.rects:
            self.canvas.delete(r)
        for t in self.texts:
            self.canvas.delete(t)
        self.rects = []
        self.texts = []

    def save_all_clips(self):
        if not self.rects:
            messagebox.showwarning("枠を1つ以上描いてください")
            return

        save_path = filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")])
        if not save_path: return

        pdf_page_info = self.doc[0]
        scale_x = pdf_page_info.rect.width / self.image.width
        scale_y = pdf_page_info.rect.height / self.image.height

        reader = PdfReader(self.pdf_path)
        writer = PdfWriter()

        for page_in in reader.pages:
            for r_id in self.rects:
                coords = self.canvas.coords(r_id)
                px1 = min(coords[0], coords[2]) * scale_x
                px2 = max(coords[0], coords[2]) * scale_x
                py1 = (self.image.height - max(coords[1], coords[3])) * scale_y
                py2 = (self.image.height - min(coords[1], coords[3])) * scale_y

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
        app = NumberedPdfCropperApp(root, path)
        root.mainloop()
    else:
        root.destroy()