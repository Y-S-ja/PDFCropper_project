import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import fitz  # PyMuPDF
from pypdf import PdfReader, PdfWriter
import os

class PdfCropperApp:
    def __init__(self, root, pdf_path):
        self.root = root
        self.root.title("自作PDFカッター")
        self.pdf_path = pdf_path

        # --- 1. プレビュー画像の準備 (Step 2) ---
        self.doc = fitz.open(pdf_path)
        self.page_idx = 0
        self.zoom = 2.0  # 2倍の解像度でプレビュー作成
        
        # プレビュー用の一時画像を作成
        pix = self.doc[self.page_idx].get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom))
        self.preview_path = "temp_preview.png"
        pix.save(self.preview_path)

        # --- 2. GUIの配置 (Step 3 & 4) ---
        self.image = Image.open(self.preview_path)
        self.tk_image = ImageTk.PhotoImage(self.image)

        self.canvas = tk.Canvas(root, width=self.image.width, height=self.image.height, cursor="cross")
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image)

        # 保存ボタン
        self.btn_save = tk.Button(root, text="この範囲でPDFを保存", command=self.save_cropped_pdf)
        self.btn_save.pack(pady=10)

        # 状態管理
        self.rect = None # クリックによる範囲指定領域
        self.start_x = self.start_y = 0
        self.end_x = self.end_y = 0

        # マウスイベントのバインド
        self.canvas.bind("<Button-1>", self.on_press) # 左クリック
        self.canvas.bind("<B1-Motion>", self.on_move) # 左ドラッグ

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        if self.rect: # すでに範囲指定領域が存在する場合は削除
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, event.x, event.y, outline="red", width=2)

    def on_move(self, event):
        self.end_x, self.end_y = event.x, event.y
        self.canvas.coords(self.rect, self.start_x, self.start_y, self.end_x, self.end_y)

    def save_cropped_pdf(self):
        # --- 3. 座標の変換とPDF保存 (Step 1 & 5) ---
        if not self.rect: # 範囲指定領域が存在しない場合は警告
            messagebox.showwarning("警告", "範囲を選択してください")
            return

        # 画面のピクセル座標をPDFのポイント座標に変換
        # PDFの本来のサイズを取得
        pdf_page = self.doc[self.page_idx]
        pdf_width = pdf_page.rect.width
        pdf_height = pdf_page.rect.height

        # 倍率を計算 (画面上の1ピクセルがPDFの何ポイントか)
        scale_x = pdf_width / self.image.width
        scale_y = pdf_height / self.image.height

        # 座標変換 (PDFは左下が0,0、Canvasは左上が0,0なので注意)
        pdf_x1 = min(self.start_x, self.end_x) * scale_x
        pdf_x2 = max(self.start_x, self.end_x) * scale_x
        
        # Y軸は反転させる必要がある
        pdf_y1 = (self.image.height - max(self.start_y, self.end_y)) * scale_y
        pdf_y2 = (self.image.height - min(self.start_y, self.end_y)) * scale_y

        # pypdfを使って切り抜き実行
        reader = PdfReader(self.pdf_path)
        writer = PdfWriter()
        
        for p in reader.pages: # 同じ範囲で繰り返し切り抜く
            p.mediabox.lower_left = (pdf_x1, pdf_y1)
            p.mediabox.upper_right = (pdf_x2, pdf_y2)
            writer.add_page(p)

        output_filename = "final_output.pdf"
        with open(output_filename, "wb") as f:
            writer.write(f)

        messagebox.showinfo("成功", f"{output_filename} を保存しました！")

if __name__ == "__main__":
    root = tk.Tk()
    app = PdfCropperApp(root, "input.pdf")
    root.mainloop()