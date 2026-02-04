import tkinter as tk
from PIL import Image, ImageTk  # 画像を扱うためのライブラリ

def create_window():
    # 1. メインウィンドウ（土台）の作成
    root = tk.Tk()
    root.title("PDF分割アプリ - プレビュー画面")

    # 2. 表示する画像を読み込む
    # step2で作ったPNGファイルを開く
    img = Image.open("page_preview.png")
    
    # Tkinterで表示できる形式に変換する
    tk_img = ImageTk.PhotoImage(img)

    # 3. 画像を表示するための「ラベル」を作る
    # ラベルは文字だけでなく画像も載せられる「入れ物」です
    label = tk.Label(root, image=tk_img)
    label.pack() # 画面の中央に配置する

    # 4. ボタンを1つ置いてみる
    # 閉じるボタンを作ってみます
    button = tk.Button(root, text="アプリを閉じる", command=root.destroy)
    button.pack(pady=10) # 少し余白(pady)を空けて配置

    # 5. メインループの開始
    # これを書かないと、ウィンドウが一瞬で消えてしまいます
    # 「ユーザーが何か操作するまで待機せよ」という命令です
    root.mainloop()

if __name__ == "__main__":
    create_window()