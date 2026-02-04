from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()

# reader.pages（すべてのページ）を1枚ずつ取り出して処理する
for page in reader.pages:
    width = float(page.mediabox.upper_right[0])
    height = float(page.mediabox.upper_right[1])
    
    # 全ページに対して左半分にカット
    page.mediabox.upper_right = (width / 2, height)
    
    # 処理したページを1枚ずつwriterに追加していく
    writer.add_page(page)

with open("output_all_left.pdf", "wb") as f:
    writer.write(f)

print("すべてのページを左半分にして保存しました！")