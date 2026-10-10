import os
import sys
from PySide6.QtWidgets import QApplication
from main_window import MainWindow
import traceback
from datetime import datetime

def log_exceptions(exctype, value, tb):
    error_message = "".join(traceback.format_exception(exctype, value, tb))

    # exeファイルが置かれているフォルダの絶対パスを取得
    if getattr(sys, 'frozen', False):
        # exe化されている場合：exeファイルがあるフォルダ
        app_dir = os.path.dirname(sys.executable)
    else:
        # 通常の .py 実行の場合：このスクリプトがあるフォルダ
        app_dir = os.path.dirname(os.path.abspath(__file__))

    # ログファイルの保存先を「app_dir/error.log」に固定する
    log_path = os.path.join(app_dir, "error.log")

    # 追記モード("a")で書き込み
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"\n--- エラー発生日時: {datetime.now()} ---\n")
        f.write(error_message)

if __name__ == "__main__":
    sys.excepthook = log_exceptions
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())