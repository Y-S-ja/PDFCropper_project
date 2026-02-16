import sys
import os
import fitz
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QPushButton, QFileDialog, QMessageBox, QGraphicsView, 
                             QGraphicsScene, QGraphicsRectItem, QHBoxLayout, QLabel)
from PySide6.QtCore import Qt, QRectF, QPointF, QVariantAnimation, QTimer, QEasingCurve
from PySide6.QtGui import QPixmap, QImage, QPen, QColor, QBrush

# --- 1. スマートな枠（アイテム）クラス ---
class myCropBox(QGraphicsRectItem):
    HANDLE_SIZE = 10.0  # ハンドルのサイズ
    HANDLE_TOP_LEFT = 1
    HANDLE_TOP_RIGHT = 2
    HANDLE_BOTTOM_LEFT = 3
    HANDLE_BOTTOM_RIGHT = 4

    def __init__(self, rect):
        super().__init__(rect)
        self.setPen(QPen(QColor(0, 120, 215), 2, Qt.DashLine))
        self.setBrush(QBrush(QColor(0, 120, 215, 20)))
        
        # フラグ設定: 移動可能、選択可能、フォーカス可能にする
        self.setFlags(
            QGraphicsRectItem.ItemIsMovable |
            QGraphicsRectItem.ItemIsSelectable |
            QGraphicsRectItem.ItemSendsGeometryChanges
        )
        # マウスの動きを監視する設定（カーソル変更のため）
        self.setAcceptHoverEvents(True)
        # self.is_resizing = False
        self.active_handle = None
    
    # def itemChange(self, change, value):
    #     # 位置が変わった時に通知する設定がされている場合
    #     if change == QGraphicsRectItem.ItemPositionHasChanged:
    #         # アイテムが動いたら「見た目のキャンバス範囲」を広げる（物理的な壁はまだ動かさない）
    #         if self.scene() and self.scene().views():
    #             for view in self.scene().views():
    #                 if hasattr(view, "update_scene_limit"):
    #                     view.update_scene_limit(force_physical=False)
    #     return super().itemChange(change, value)
    
    def boundingRect(self):
        # 本来の四角形よりハンドルの半分サイズ分だけ外側まで「自分の領域」とする
        margin = self.HANDLE_SIZE
        return self.rect().adjusted(-margin, -margin, margin, margin)

    def paint(self, painter, option, widget):
        # 標準の四角を描画
        # super().paint(painter, option, widget)
        # 標準の四角を描画
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawRect(self.rect())
        
        # 選択されている時だけハンドルを描画
        if self.isSelected():
            painter.setPen(QPen(QColor(0, 120, 215), 1))
            painter.setBrush(Qt.white)
            r = self.rect()
            # 四隅にハンドルを描く
            for pt in [r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()]:
                painter.drawRect(QRectF(pt.x() - self.HANDLE_SIZE/2, 
                                        pt.y() - self.HANDLE_SIZE/2, 
                                        self.HANDLE_SIZE, self.HANDLE_SIZE))

    # --- 修正2: 4隅すべてのハンドルを判定する ---
    def get_handle_at(self, pos):
        r = self.rect()
        s = self.HANDLE_SIZE
        handles = {
            self.HANDLE_TOP_LEFT: QRectF(r.topLeft().x()-s, r.top()-s, s*2, s*2),
            self.HANDLE_TOP_RIGHT: QRectF(r.right()-s, r.top()-s, s*2, s*2),
            self.HANDLE_BOTTOM_LEFT: QRectF(r.left()-s, r.bottom()-s, s*2, s*2),
            self.HANDLE_BOTTOM_RIGHT: QRectF(r.right()-s, r.bottom()-s, s*2, s*2),
        }
        for handle_id, rect in handles.items():
            if rect.contains(pos):
                return handle_id
        return None

    def hoverMoveEvent(self, event):
        # マウスが四隅の近くにあるかチェックしてカーソルを変える
        handle_id = self.get_handle_at(event.pos())
        if handle_id:
            if handle_id==1 or handle_id==4:
                self.setCursor(Qt.SizeFDiagCursor)
            if handle_id==2 or handle_id==3:
                self.setCursor(Qt.SizeBDiagCursor)
        else:
            self.setCursor(Qt.SizeAllCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event):
        # クリックした場所が「ハンドル」の上なら変形モードへ
        handle = self.get_handle_at(event.pos())
        if handle:
            self.active_handle = handle
            # self.is_resizing = True
            event.accept()
        else:
            # self.is_resizing = False
            self.active_handle = None
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.active_handle:
            self.prepareGeometryChange()
            rect = self.rect()
            pos = event.pos()
            
            # 現在のハンドルに合わせて頂点を動かす
            if self.active_handle == self.HANDLE_TOP_LEFT:
                rect.setTopLeft(pos)
            elif self.active_handle == self.HANDLE_TOP_RIGHT:
                rect.setTopRight(pos)
            elif self.active_handle == self.HANDLE_BOTTOM_LEFT:
                rect.setBottomLeft(pos)
            elif self.active_handle == self.HANDLE_BOTTOM_RIGHT:
                rect.setBottomRight(pos)

            # --- 0をまたいだ時のハンドル入れ替えロジック ---
            # 左右が逆転した場合
            if rect.width() < 0:
                swap_map = {
                    self.HANDLE_TOP_LEFT: self.HANDLE_TOP_RIGHT,
                    self.HANDLE_TOP_RIGHT: self.HANDLE_TOP_LEFT,
                    self.HANDLE_BOTTOM_LEFT: self.HANDLE_BOTTOM_RIGHT,
                    self.HANDLE_BOTTOM_RIGHT: self.HANDLE_BOTTOM_LEFT
                }
                self.active_handle = swap_map.get(self.active_handle, self.active_handle)
            
            # 上下が逆転した場合
            if rect.height() < 0:
                swap_map = {
                    self.HANDLE_TOP_LEFT: self.HANDLE_BOTTOM_LEFT,
                    self.HANDLE_BOTTOM_LEFT: self.HANDLE_TOP_LEFT,
                    self.HANDLE_TOP_RIGHT: self.HANDLE_BOTTOM_RIGHT,
                    self.HANDLE_BOTTOM_RIGHT: self.HANDLE_TOP_RIGHT
                }
                self.active_handle = swap_map.get(self.active_handle, self.active_handle)

            # 常に「正のサイズ」としてセット（これで描画が消えなくなる）
            self.setRect(rect.normalized())
            
            # 変形中もキャンバスを広げる
            # if self.scene() and self.scene().views():
            #     for view in self.scene().views():
            #         if hasattr(view, "update_scene_limit"):
            #             view.update_scene_limit(force_physical=False)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # self.is_resizing = False
        # 最後に形を整える（幅や高さがマイナスの状態を直す）
        self.setRect(self.rect().normalized())
        super().mouseReleaseEvent(event)
