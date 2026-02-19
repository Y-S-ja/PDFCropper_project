import sys
import os
import fitz
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QPushButton, QFileDialog, QMessageBox, QGraphicsView, 
                             QGraphicsScene, QGraphicsRectItem, QHBoxLayout, QLabel)
from PySide6.QtCore import Qt, QRectF, QPointF, QVariantAnimation, QTimer, QEasingCurve
from PySide6.QtGui import QPixmap, QImage, QPen, QColor, QBrush, QPainterPath

# --- 1. スマートな枠（アイテム）クラス ---
class myCropBox(QGraphicsRectItem):
    HANDLE_SIZE = 10.0  # ハンドルのサイズ
    # ハンドル定数をビットフラグに変更 (1枚目: 0=Left, 1=Right / 2枚目: 0=Top, 2=Bottom)
    HANDLE_TOP_LEFT = 0     # 00
    HANDLE_TOP_RIGHT = 1    # 01
    HANDLE_BOTTOM_LEFT = 2  # 10
    HANDLE_BOTTOM_RIGHT = 3 # 11

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

    def paint(self, painter, option, widget):
        # 標準の四角を描画
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawRect(self.rect())
        
        # 選択されている時だけハンドルを描画
        if self.isSelected():
            # ハンドルもズームで太さが変わらないようにする
            h_pen = QPen(QColor(0, 120, 215), 3)
            h_pen.setCosmetic(True)
            painter.setPen(h_pen)
            painter.setBrush(Qt.white)
            # 各ハンドルの矩形を描画
            for h_rect in self.get_handle_rects().values():
                painter.drawRect(h_rect)

    def get_handle_at(self, pos):
        """指定された座標にあるハンドルのIDを返す"""
        for handle_id, rect in self.get_handle_rects().items():
            if rect.contains(pos):
                return handle_id
        return None

    def hoverMoveEvent(self, event):
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
        # クリックした場所が「ハンドル」の上なら変形モードへ
        handle = self.get_handle_at(event.pos())
        if handle is not None:
            self.active_handle = handle
            # self.is_resizing = True
            event.accept()
        else:
            # self.is_resizing = False
            self.active_handle = None
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.active_handle is not None:
            self.prepareGeometryChange()
            rect = self.rect()
            pos = event.pos()
            
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
        if self.active_handle is not None:
            self.setRect(self.rect().normalized())
        super().mouseReleaseEvent(event)
