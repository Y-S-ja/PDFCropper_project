from pypdf import PdfReader, PdfWriter, Transformation
import copy

# 1. PDFを読み込む
reader = PdfReader("input.pdf")
writer = PdfWriter()

# 2. 最初のページを取り出す
page = reader.pages[0]

# --- PDFのサイズ情報を取得 ---
# mediabox はページの「物理的な枠」を表します
# [左下のX, 左下のY, 右上のX, 右上のY] の順
original_upper_right = page.mediabox.upper_right # (横幅, 高さ)
width = float(original_upper_right[0])
height = float(original_upper_right[1])

print(f"元のサイズ: 横 {width}pt, 縦 {height}pt")

# 3. 切り抜き範囲（クロップ）の設定
# ページを複製して、表示範囲（mediabox）を書き換えることで「切り抜き」を実現します
# ここでは「左半分」を指定してみます
# 設定：左下(0, 0) から 右上(幅の半分, 高さ) まで
page.mediabox.lower_left = (0, 0)
page.mediabox.upper_right = (width / 2, height)

# 4. 書き出し用のオブジェクトに追加
writer.add_page(page)

# 5. ファイルを保存
with open("output_left.pdf", "wb") as f:
    writer.write(f)

print("保存が完了しました！")