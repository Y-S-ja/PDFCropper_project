from pypdf import PdfReader, PdfWriter
import copy

reader = PdfReader("input.pdf")
writer = PdfWriter()

for page in reader.pages:
    # --- 左ページ用の処理 ---
    # 元のページをコピーして「左用」を作る
    left_page = copy.copy(page)
    width = float(left_page.mediabox.upper_right[0])
    height = float(left_page.mediabox.upper_right[1])
    
    # 左半分だけに枠を絞る
    left_page.mediabox.upper_right = (width / 2, height)
    writer.add_page(left_page) # 左ページを追加

    # --- 右ページ用の処理 ---
    # もう一度元のページをコピーして「右用」を作る
    right_page = copy.copy(page)
    
    # 右半分だけに枠を絞る (左下を中央に、右上は元のまま)
    right_page.mediabox.lower_left = (width / 2, 0)
    writer.add_page(right_page) # 右ページを追加

with open("output_split.pdf", "wb") as f:
    writer.write(f)

print("1ページを左右に分割して保存しました！")