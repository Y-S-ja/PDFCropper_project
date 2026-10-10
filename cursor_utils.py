import functools
from contextlib import contextmanager
from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import QApplication


@contextmanager
def wait_cursor():
    """
    UIスレッド（メインスレッド）でのみ砂時計カーソル（Qt.WaitCursor）を表示し、
    完了時または例外発生時に確実に元のカーソルへ復元するコンテキストマネージャ。
    ワーカースレッドから呼ばれた場合はUIに干渉せず安全にパススルーします。
    """
    app = QApplication.instance()
    is_gui_thread = app is not None and (QThread.currentThread() == app.thread())

    if is_gui_thread:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        # カーソル変更を即座にOS/ウィンドウへ反映
        QApplication.processEvents()
        try:
            yield
        finally:
            QApplication.restoreOverrideCursor()
    else:
        yield


def with_wait_cursor(func):
    """メインスレッドから実行された場合に自動で砂時計カーソルにするデコレータ"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with wait_cursor():
            return func(*args, **kwargs)
    return wrapper


def auto_wrap_class_methods(target_cls, exclude_names=None):
    """
    対象クラスのすべての公開メソッド（静的メソッド含む）を、
    自動的に with_wait_cursor 付きのラッパーで置き換える。
    """
    exclude = set(exclude_names or [])
    for attr_name in dir(target_cls):
        if attr_name.startswith("_") or attr_name in exclude:
            continue
        attr = getattr(target_cls, attr_name)
        if callable(attr):
            wrapped = with_wait_cursor(attr)
            setattr(target_cls, attr_name, staticmethod(wrapped))
