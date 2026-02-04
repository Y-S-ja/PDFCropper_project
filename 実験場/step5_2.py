import tkinter as tk
from tkinter import messagebox, filedialog
from PIL import Image, ImageTk
import fitz  # PyMuPDF
from pypdf import PdfReader, PdfWriter

try: # 実行してみる
    from ctypes import windll
    windll.shcore.SetProcessDpiAwareness(1)
except: # 失敗したら何もしない
    pass

class PdfCropperApp:
    def __init__(self, root, pdf_path):
        self.root = root
        self.root.title("自作PDFカッター（サイズ調整版）")
        self.pdf_path = pdf_path

        # --- 1. プレビュー画像の準備 ---
        self.doc = fitz.open(pdf_path)
        self.page_idx = 0
        
        # 高画質(zoom=2.0)で生成するが、表示は画面に合わせる
        zoom = 2.0
        pix = self.doc[self.page_idx].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img_full = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        # 画面からはみ出さないようにリサイズ（最大高さを600pxに制限）
        max_display_height = 600
        if img_full.height > max_display_height:
            ratio = max_display_height / img_full.height
            new_width = int(img_full.width * ratio)
            self.image = img_full.resize((new_width, max_display_height), Image.LANCZOS)
        else:
            self.image = img_full

        self.tk_image = ImageTk.PhotoImage(self.image)

        # --- 2. レイアウトの変更 ---
        # ボタンを先に「上」に配置（画像が大きくても見切れない）
        self.toolbar = tk.Frame(root)
        self.toolbar.pack(side="top", fill="x", padx=10, pady=5)

        self.btn_save = tk.Button(self.toolbar, text="この範囲でPDFを保存", command=self.save_cropped_pdf, bg="lightblue")
        self.btn_save.pack(side="left")

        # キャンバス（画像表示）を下に配置
        self.canvas = tk.Canvas(root, width=self.image.width, height=self.image.height, cursor="cross", bg="gray")
        self.canvas.pack(side="top", padx=10, pady=10)
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image)

        # 状態管理
        self.rect = None
        self.start_x = self.start_y = 0
        self.end_x = self.end_y = 0

        # マウスイベント
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_move)

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        if self.rect: self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, event.x, event.y, outline="red", width=2)

    def on_move(self, event):
        self.end_x, self.end_y = event.x, event.y
        self.canvas.coords(self.rect, self.start_x, self.start_y, self.end_x, self.end_y)

    def save_cropped_pdf(self):
        if not self.rect:
            messagebox.showwarning("警告", "範囲を選択してください")
            return

        # --- 3. 座標の変換（重要：表示倍率を考慮） ---
        pdf_page = self.doc[self.page_idx]
        
        # 「PDFの本来のサイズ」と「今画面に見えているサイズ」の比率を計算
        scale_x = pdf_page.rect.width / self.image.width
        scale_y = pdf_page.rect.height / self.image.height

        # 座標の計算（Y軸反転を含む）
        pdf_x1 = min(self.start_x, self.end_x) * scale_x
        pdf_x2 = max(self.start_x, self.end_x) * scale_x
        pdf_y1 = (self.image.height - max(self.start_y, self.end_y)) * scale_y
        pdf_y2 = (self.image.height - min(self.start_y, self.end_y)) * scale_y

        # PDFの保存
        reader = PdfReader(self.pdf_path)
        writer = PdfWriter()
        for p in reader.pages:
            p.mediabox.lower_left = (pdf_x1, pdf_y1)
            p.mediabox.upper_right = (pdf_x2, pdf_y2)
            writer.add_page(p)

        output_filename = filedialog.asksaveasfilename(
            title="保存先を選択してください。",
            defaultextension=".pdf",
            filetypes=[("PDF files", ".pdf")]
        )
        with open(output_filename, "wb") as f:
            writer.write(f)

        messagebox.showinfo("成功", f"保存完了しました！\n{output_filename}")

if __name__ == "__main__":
    root = tk.Tk()
    
    # ウィンドウを一時的に隠す（ダイアログだけを綺麗に出すため）
    root.withdraw()

    # ファイル選択ダイアログを表示
    pdf_path = filedialog.askopenfilename(
        title="PDFファイルを選択してください",
        filetypes=[("PDF files", "*.pdf")] # PDFだけを表示するフィルタ
    )

    # ファイルが選択された場合のみアプリを起動
    if pdf_path:
        root.deiconify() # ウィンドウを再表示
        app = PdfCropperApp(root, pdf_path)
        root.mainloop()
    else:
        # 選択されなかった（キャンセルされた）場合は終了
        root.destroy()