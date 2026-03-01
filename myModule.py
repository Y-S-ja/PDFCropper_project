import sys
import os
import fitz
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QPushButton, QFileDialog, QMessageBox, QGraphicsView, 
                             QGraphicsScene, QGraphicsRectItem, QHBoxLayout, QLabel,
                             QGraphicsSimpleTextItem, QGraphicsItem, QMenuBar, QMenu,
                             QGraphicsObject, QGraphicsPixmapItem)
from PySide6.QtCore import Qt, QRectF, QPointF, QVariantAnimation, QTimer, QEasingCurve, QEvent, Signal
from PySide6.QtGui import QPixmap, QImage, QPen, QColor, QBrush, QPainterPath
from PySide6 import QtGui

# --- 1. スマートな枠（アイテム）クラス ---
class myCropBox(QGraphicsObject):
    geometryChanged = Signal(object) # 自身(item)を渡す
    deltaResized = Signal(object, int, QPointF) # item, handle_id, delta_scene
    transformationFinished = Signal(object) # 変形(リサイズ)完了通知
    
    HANDLE_SIZE = 10.0  # ハンドルのサイズ
    # ハンドル定数をビットフラグに変更 (1枚目: 0=Left, 1=Right / 2枚目: 0=Top, 2=Bottom)
    HANDLE_TOP_LEFT = 0     # 00
    HANDLE_TOP_RIGHT = 1    # 01
    HANDLE_BOTTOM_LEFT = 2  # 10
    HANDLE_BOTTOM_RIGHT = 3 # 11

    def __init__(self, rect):
        super().__init__()
        self._rect = rect
        self.pen_style = QPen(QColor(0, 120, 215), 2, Qt.DashLine)
        self.brush_style = QBrush(QColor(0, 120, 215, 20))
        
        # フラグ設定: 移動可能、選択可能、フォーカス可能にする
        self.setFlags(
            QGraphicsItem.ItemIsMovable |
            QGraphicsItem.ItemIsSelectable |
            QGraphicsItem.ItemSendsGeometryChanges
        )
        # マウスの動きを監視する設定（カーソル変更のため）
        self.setAcceptHoverEvents(True)
        self.active_handle = None
        self._block_sync = False # 循環防止用
        self.allowed_rect = None # 移動・変形を制限する領域 (NoneならPDF全体)
        self.last_mouse_scene_pos = QPointF()
        
        # --- ハンドル（小四角）を子アイテムとして作成 ---
        self.handle_items = {}
        for h_id in [self.HANDLE_TOP_LEFT, self.HANDLE_TOP_RIGHT, 
                     self.HANDLE_BOTTOM_LEFT, self.HANDLE_BOTTOM_RIGHT]:
            h_item = QGraphicsRectItem(-self.HANDLE_SIZE/2, -self.HANDLE_SIZE/2, 
                                       self.HANDLE_SIZE, self.HANDLE_SIZE, parent=self)
            h_item.setBrush(Qt.white)
            pen = QPen(QColor(0, 120, 215), 3)
            pen.setCosmetic(True)
            h_item.setPen(pen)
            h_item.setFlag(QGraphicsItem.ItemIgnoresTransformations)
            h_item.setZValue(2) # ハンドルは最前面 (badgeより上)
            h_item.hide()
            self.handle_items[h_id] = h_item
        
        # 初期位置をハンドルに反映させるために明示的に呼び出す
        self.setRect(rect)
        
    def rect(self):
        return self._rect

    def setRect(self, rect):
        """矩形のサイズが変更されたらハンドルとバッジの位置も更新する"""
        self._rect = QRectF(rect)
        self.prepareGeometryChange()
        # 1. ハンドルの位置を更新
        if hasattr(self, 'handle_items'):
            self.handle_items[self.HANDLE_TOP_LEFT].setPos(rect.topLeft())
            self.handle_items[self.HANDLE_TOP_RIGHT].setPos(rect.topRight())
            self.handle_items[self.HANDLE_BOTTOM_LEFT].setPos(rect.bottomLeft())
            self.handle_items[self.HANDLE_BOTTOM_RIGHT].setPos(rect.bottomRight())

        # 2. 子要素の中からバッジを探して位置を合わせる
        for child in self.childItems():
            if isinstance(child, myBadge):
                child.setPos(rect.topLeft())
        
        if not self._block_sync:
            self.geometryChanged.emit(self)

    def pen(self): return self.pen_style
    def setPen(self, pen): self.pen_style = pen; self.update()
    def brush(self): return self.brush_style
    def setBrush(self, brush): self.brush_style = brush; self.update()

    def get_current_scale(self):
        """現在のビューのズーム倍率を取得する"""
        if self.scene() and self.scene().views():
            # 最初のビューの現在のスケーリング（m11）を返す
            return self.scene().views()[0].transform().m11()
        return 1.0

    def get_handle_rects(self):
        """全てのハンドルの現在の矩形座標を辞書で返す（ズームに応じてサイズを補正）"""
        r = self.rect()
        scale = self.get_current_scale()
        # 画面上で常に一定のサイズ（HANDLE_SIZE）に見えるように逆算する
        s = self.HANDLE_SIZE / scale
        s2 = s / 2
        return {
            self.HANDLE_TOP_LEFT: QRectF(r.left()-s2, r.top()-s2, s, s),
            self.HANDLE_TOP_RIGHT: QRectF(r.right()-s2, r.top()-s2, s, s),
            self.HANDLE_BOTTOM_LEFT: QRectF(r.left()-s2, r.bottom()-s2, s, s),
            self.HANDLE_BOTTOM_RIGHT: QRectF(r.right()-s2, r.bottom()-s2, s, s),
        }

    def boundingRect(self):
        # ハンドルの中心が頂点にあるため、実際にはみ出すのはサイズの半分。
        # 余計な「空き地」を作らないよう、正確なマージンを設定する。
        scale = self.get_current_scale()
        margin = (self.HANDLE_SIZE / scale) / 2
        return self.rect().adjusted(-margin, -margin, margin, margin)

    def shape(self):
        """正確な当たり判定の形を定義。
        中央の矩形 ＋ 各ハンドルの矩形のみを統合して正確な形状を作る。"""
        path = QPainterPath()
        # 重なり部分が「穴あき」にならないようにルールを変更
        path.setFillRule(Qt.WindingFill)
        
        # 1. メインの矩形部分を追加
        path.addRect(self.rect())
        # 2. 選択中なら、各ハンドルの矩形部分だけをピンポイントで追加
        if self.isSelected():
            for h_rect in self.get_handle_rects().values():
                path.addRect(h_rect)
        return path

    def get_bg_rect(self):
        """制限領域を取得する（個別設定があればそれを優先、なければPDF背景）"""
        if self.allowed_rect is not None:
            return self.allowed_rect
            
        if self.scene():
            for item in self.scene().items():
                if isinstance(item, QGraphicsPixmapItem):
                    return item.boundingRect()
        return None

    def normalize_geometry(self):
        """見た目の位置・サイズを維持したまま、内部のズレ(rect.topLeft)を pos に吸収させる"""
        rect = self.rect().normalized()
        delta = rect.topLeft()
        
        if delta != QPointF(0, 0):
            self._block_sync = True # 内部調整による再同期を防ぐ
            self.setPos(self.pos() + delta)
            # rect を (0,0) 起点の正のサイズに作り直す
            norm_rect = QRectF(0, 0, rect.width(), rect.height())
            self.setRect(norm_rect)
            self._block_sync = False
        else:
            self.setRect(rect)

    def apply_delta(self, handle_id, delta_scene):
        """外部（同期など）から移動ベクトルを受け取って自身を変形させる"""
        self.prepareGeometryChange()
        rect = self.rect()
        
        # シーン上の差分をローカルの差分に変換（スケーリングの影響を排除するため）
        # ただし現在はスケーリングがない前提なので、delta_scene をそのまま使える
        dx = delta_scene.x()
        dy = delta_scene.y()
        
        if handle_id & 1: rect.setRight(rect.right() + dx)
        else: rect.setLeft(rect.left() + dx)
        
        if handle_id & 2: rect.setBottom(rect.bottom() + dy)
        else: rect.setTop(rect.top() + dy)
        
        # 反転判定は行わず、正規化だけしてセットする
        # (同期中に handle_id が変わると収拾がつかなくなるため)
        self.setRect(rect.normalized())

    def paint(self, painter, option, widget):
        # 標準の四角を描画
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawRect(self.rect())

    def itemChange(self, change, value):
        """選択状態が変わった瞬間にハンドルの表示・非表示を切り替える"""
        if change == QGraphicsItem.ItemSelectedChange:
            # value は新しく設定される選択状態 (bool)
            is_sel = bool(value)
            if hasattr(self, 'handle_items'):
                for h_item in self.handle_items.values():
                    h_item.setVisible(is_sel)
            
            # 選択されている枠を最前面に持ってくる
            if is_sel:
                self.setZValue(1000)
            else:
                self.setZValue(0)
        
        if change == QGraphicsItem.ItemPositionChange and self.scene():
            # 1. 移動制限：PDFの範囲内に収める
            new_pos = value # cropbox.pos()の移動先
            bg_rect = self.get_bg_rect()
            if bg_rect:
                rect = self.rect()
                x = max(bg_rect.left(), min(new_pos.x(), bg_rect.right() - rect.width()))
                y = max(bg_rect.top(), min(new_pos.y(), bg_rect.bottom() - rect.height()))
                return QPointF(x, y) # ここは補正値を返す必要があるため return して良い

        if change == QGraphicsItem.ItemPositionHasChanged:
            # 2. 確定後の座標を同期させる
            if not getattr(self, '_block_sync', False):
                self.geometryChanged.emit(self)
        
        return super().itemChange(change, value)

    def get_handle_at(self, pos):
        """指定された座標にあるハンドルのIDを返す"""
        for handle_id, rect in self.get_handle_rects().items():
            if rect.contains(pos):
                return handle_id
        return None

    def hoverMoveEvent(self, event):
        # 選択されていない時はハンドル判定を行わない（カーソルを変えない）
        if not self.isSelected():
            self.setCursor(Qt.SizeAllCursor)
            super().hoverMoveEvent(event)
            return

        # マウスが四隅の近くにあるかチェックしてカーソルを変える
        handle_id = self.get_handle_at(event.pos())
        if handle_id is not None:
            if handle_id == 0 or handle_id == 3:
                self.setCursor(Qt.SizeFDiagCursor)
            if handle_id == 1 or handle_id == 2:
                self.setCursor(Qt.SizeBDiagCursor)
        else:
            self.setCursor(Qt.SizeAllCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        # 選択されていない時はハンドル判定を行わない（まず選択させる）
        if not self.isSelected():
            self.active_handle = None
            super().mousePressEvent(event)
            return

        # クリックした場所が「ハンドル」の上なら変形モードへ
        handle = self.get_handle_at(event.pos())
        if handle is not None:
            self.active_handle = handle
            
            # --- 重要：始点を「クリック位置」ではなく「現在の辺の位置」にする ---
            # これにより、最初の mouseMoveEvent で発生する「吸着（スナップ）」も
            # 正しいベクトルとして deltaResized に含まれるようになる。
            rect = self.rect()
            handle_pos = QPointF()
            handle_pos.setX(rect.right() if handle & 1 else rect.left())
            handle_pos.setY(rect.bottom() if handle & 2 else rect.top())
            
            self.last_mouse_scene_pos = self.mapToScene(handle_pos)
            event.accept()
        else:
            # self.is_resizing = False
            self.active_handle = None
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.active_handle is not None:
            self.prepareGeometryChange()
            rect = self.rect()
            
            # マウス位置をシーン座標で取得し、制限
            bg_rect = self.get_bg_rect()
            current_scene_pos = self.mapToScene(event.pos())
            if bg_rect:
                current_scene_pos.setX(max(bg_rect.left(), min(current_scene_pos.x(), bg_rect.right())))
                current_scene_pos.setY(max(bg_rect.top(), min(current_scene_pos.y(), bg_rect.bottom())))
            
            # ベクトル（差分）を計算
            delta_scene = current_scene_pos - self.last_mouse_scene_pos
            self.last_mouse_scene_pos = current_scene_pos
            
            # ローカルの座標系での移動量に変換
            pos = self.mapFromScene(current_scene_pos)
            
            # ビットフラグを使って頂点を更新 (1bit目が1ならRight, 2bit目が1ならBottom)
            # self.active_handleが01, 11なら条件式は01を返す
            # self.active_handleが00, 10なら条件式は00を返す
            if self.active_handle & 1: rect.setRight(pos.x())
            else: rect.setLeft(pos.x())
            
            # self.active_handleが10, 11なら条件式は10を返す
            # self.active_handleが00, 01なら条件式は00を返す
            if self.active_handle & 2: rect.setBottom(pos.y())
            else: rect.setTop(pos.y())

            # --- 0をまたいだ時の反転ロジック (XORでビットを反転させるだけ) ---
            if rect.width() < 0:  self.active_handle ^= 1 # 左右反転、1ビット目を反転させる
            if rect.height() < 0: self.active_handle ^= 2 # 上下反転、2ビット目を反転させる

            # 常に「正のサイズ」としてセット
            self.setRect(rect.normalized())
            
            # 同期用の信号（現在のハンドル状態と移動ベクトルを添えて）
            if not self._block_sync:
                self.deltaResized.emit(self, self.active_handle, delta_scene)
            
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # 変形完了時に、矩形の左上のズレを pos に吸収させて (0,0) 起点に戻す
        was_resizing = self.active_handle is not None
        if was_resizing:
            self.normalize_geometry()

        self.active_handle = None
        super().mouseReleaseEvent(event)
        
        # 変形が完全に終了したことを通知
        if was_resizing:
            self.transformationFinished.emit(self)

class myBadge(QGraphicsRectItem):
    """切り抜き枠に付与する番号バッジクラス"""
    def __init__(self, index, size, parent=None):
        super().__init__(0, 0, size, size, parent=parent)
        self.setBrush(QBrush(QColor(0, 120, 215)))
        self.setPen(Qt.NoPen)
        # ズームしても大きさが変わらないように設定
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(1) # バッジは枠(Z=0)より上、ハンドル(Z=2)より下
        
        self.text_item = QGraphicsSimpleTextItem(str(index), parent=self)
        self.text_item.setBrush(QBrush(Qt.white))
        self.update_text_pos()

    def update_text_pos(self):
        # バッジ内でのテキスト中央寄せ
        brect = self.text_item.boundingRect()
        self.text_item.setPos((self.rect().width() - brect.width())/2, (self.rect().height() - brect.height())/2)

    def set_number(self, index):
        self.text_item.setText(str(index))
        self.update_text_pos()

class HoverMenuBar(QMenuBar):
    """ホバーで展開・クローズを制御するカスタムメニューバー"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_clicked = False
        self._active_hover_menu = None
        self.setMouseTracking(True) # マウス移動を常に監視

    def addMenu(self, title):
        menu = super().addMenu(title)
        # メニュー自体にイベントフィルターを設置して、マウスの出入りを監視する
        menu.installEventFilter(self)
        return menu
        print("DEBUG: addMenu")

    def eventFilter(self, obj, event):
        # QMenu自体へのイベントを監視
        if isinstance(obj, QMenu):
            if event.type() == QEvent.Leave:
                # クリックモードでなければ、マウスが完全に外に出たか判定して閉じる
                if not self._is_clicked:
                    # 少し遅延させて「別のメニュー項目へ移動中」かどうかを確認する
                    QTimer.singleShot(50, lambda: self._check_should_hide(obj))
        return super().eventFilter(obj, event)
        print("eventFilter")

    def _check_should_hide(self, menu):
        """マウスの位置を確認し、メニューバーにもメニュー自体にもいなければ閉じる"""
        if self._is_clicked: return
        
        # 現在のマウス下のウィジェットを取得
        pos = QtGui.QCursor.pos()
        widget = QApplication.widgetAt(pos)
        
        # マウスがメニューバー上、またはメニュー自体の上にいないなら閉じる
        if widget != self and widget != menu and not menu.rect().contains(menu.mapFromGlobal(pos)):
            menu.hide()

    def mousePressEvent(self, event):
        # 項目がある部分をクリックした時だけクリックモードにする
        action = self.actionAt(event.position().toPoint())
        if action:
            print(f"DEBUG: Clicked on {action.text()} -> Stick mode")
            self._is_clicked = True
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # ホバー中にメニューを展開させる
        print(f"DEBUG: mouseMoveEvent, {self._is_clicked}")
        if not self._is_clicked:
            action = self.actionAt(event.position().toPoint())
            if action and action.menu():
                menu = action.menu()
                if not menu.isVisible():
                    # 他のホバー展開中のメニューがあれば閉じる
                    if self._active_hover_menu and self._active_hover_menu != menu:
                        self._active_hover_menu.hide()
                    
                    self._active_hover_menu = menu
                    # 正しい表示位置（項目の左下）を計算
                    rect = self.actionGeometry(action)
                    global_pos = self.mapToGlobal(rect.bottomLeft())
                    
                    print(f"DEBUG: Hover -> Showing {menu.title()}")
                    menu.popup(global_pos)
            elif not action and self._active_hover_menu:
                # 項目がない場所に移動した場合は少し待って閉じる判定
                QTimer.singleShot(50, lambda: self._check_should_hide(self._active_hover_menu))
        super().mouseMoveEvent(event) # self._is_clicked = Trueかつ、QMune表示中にホバリングによるメニュー切り替えができる

    def hideEvent(self, event):
        # メニューバーが非表示（ウィンドウ最小化など）になる際のリセット
        self._is_clicked = False
        super().hideEvent(event)

    # 各メニューが閉じられた時にフラグをリセットするための処理を追加
    def leaveEvent(self, event):
        print("DEBUG: leaveEvent")
        if not self._is_clicked and self._active_hover_menu:
            self._check_should_hide(self._active_hover_menu)
        super().leaveEvent(event)
