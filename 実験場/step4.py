import tkinter as tk
from PIL import Image, ImageTk

class SelectionApp:
    def __init__(self, root, image_path):
        self.root = root # root=tk.Tk()
        self.root.title("ステップ4: マウスで枠を描く")

        # 1. 画像の読み込み
        self.image = Image.open(image_path)
        self.tk_image = ImageTk.PhotoImage(self.image)

        # 2. Canvasの作成
        # 画像のサイズに合わせてキャンバスを作る
        self.canvas = tk.Canvas(root, width=self.image.width, height=self.image.height, cursor="cross")
        self.canvas.pack()

        # Canvasに画像を配置 (0, 0) の位置に北西(nw)基準で置く
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image)

        # 3. 状態を管理する変数
        self.rect = None      # 描画中の四角形のID
        self.start_x = None   # ドラッグ開始X
        self.start_y = None   # ドラッグ開始Y

        # 4. マウスイベントのバインド (JSのaddEventListenerに近い)
        self.canvas.bind("<Button-1>", self.on_button_press)    # 左クリック
        self.canvas.bind("<B1-Motion>", self.on_move)           # 左ドラッグ
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release) # 離した

    def on_button_press(self, event):
        # クリックした位置を記録
        self.start_x = event.x
        self.start_y = event.y
        # 新しい四角形を作成 (最初は大きさ1x1)
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x+1, self.start_y+1, 
            outline='red', width=2
        )

    def on_move(self, event):
        # ドラッグ中のマウス位置に合わせて四角形の形を更新
        cur_x, cur_y = (event.x, event.y)
        # canvas.coords(ID, x1, y1, x2, y2) で位置を書き換える
        self.canvas.coords(self.rect, self.start_x, self.start_y, cur_x, cur_y)

    def on_button_release(self, event):
        # 確定した座標をコンソールに表示してみる
        print(f"枠確定！ 開始:({self.start_x}, {self.start_y}) 終了:({event.x}, {event.y})")

if __name__ == "__main__":
    root = tk.Tk()
    app = SelectionApp(root, "page_preview.png")
    root.mainloop()