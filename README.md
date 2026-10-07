# PDFCropper

## ファイルの説明

本番仕様のmainファイル：[PDFCropper2_main.py](PDFCropper2_main.py)

## exe化について

参考：[Pythonアプリをexe化する方法 | Google AI Studio](https://aistudio.google.com/prompts/1v0SrNtmVbI9r1HOJCD13rBXxpqrEWT5g)

コマンド

``` cmd
pyinstaller --clean --noconsole PDFCropper2_main.py
```

- `--clean` : pyinstaller実行時に、不要な一時ファイルを削除する
- `--noconsole` : exe実行時のコンソールウィンドウを非表示にする
