import fitz  # PyMuPDFのこと

# 1. PDFを開く
doc = fitz.open("input.pdf")

# 2. 1ページ目（0番目）を選択
page = doc[0]

# 3. ページを画像（ピクセルデータ）に変換する
# get_pixmap() はそのページの「画像データ」を生成するメソッド
pix = page.get_pixmap()

# 4. 画像をファイルとして保存する
pix.save("page_preview.png")

# 拡大率を設定（横2倍、縦2倍）
mat = fitz.Matrix(2, 2)
pix = page.get_pixmap(matrix=mat)
pix.save("high_res_preview.png")

print("PDFの1ページ目を画像として保存しました！")

# 最後にドキュメントを閉じる
doc.close()