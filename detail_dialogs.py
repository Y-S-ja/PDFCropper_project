from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QSpinBox,
    QDialogButtonBox,
)
from PySide6.QtCore import Qt, Signal, QRect
from PySide6.QtGui import QPainter, QColor, QPen, QBrush


class GridPickerWidget(QWidget):
    """Wordライクな升目選択ウィジェット（双方向同期対応）"""

    hoverChanged = Signal(int, int)  # マウス移動で升目が変わった時
    selected = Signal(int, int)      # 升目クリック時（即確定用）

    def __init__(
        self,
        max_cols: int = 8,
        max_rows: int = 8,
        cell_size: int = 24,
        spacing: int = 4,
        parent=None,
    ):
        super().__init__(parent)
        self.max_cols = max_cols
        self.max_rows = max_rows
        self.cell_size = cell_size
        self.spacing = spacing

        self.current_cols = 2
        self.current_rows = 2

        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

        # 固定サイズを計算
        total_w = self.max_cols * (self.cell_size + self.spacing) + self.spacing
        total_h = self.max_rows * (self.cell_size + self.spacing) + self.spacing
        self.setFixedSize(total_w, total_h)

    def set_grid(self, cols: int, rows: int):
        """外部（QSpinBox等）からハイライト範囲を更新"""
        if self.current_cols != cols or self.current_rows != rows:
            self.current_cols = cols
            self.current_rows = rows
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)

        for r in range(self.max_rows):
            for c in range(self.max_cols):
                x = self.spacing + c * (self.cell_size + self.spacing)
                y = self.spacing + r * (self.cell_size + self.spacing)
                rect = QRect(x, y, self.cell_size, self.cell_size)

                # 現在選択中の範囲内ならハイライト
                is_active = (c < self.current_cols and r < self.current_rows)

                if is_active:
                    painter.setPen(QPen(QColor("#0078D7"), 1))
                    painter.setBrush(QBrush(QColor("#CCE8FF")))
                else:
                    painter.setPen(QPen(QColor("#D0D0D0"), 1))
                    painter.setBrush(QBrush(QColor("#FFFFFF")))

                painter.drawRect(rect)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        # 1-based の col / row を計算
        col = (pos.x() - self.spacing) // (self.cell_size + self.spacing) + 1
        row = (pos.y() - self.spacing) // (self.cell_size + self.spacing) + 1

        col = max(1, min(col, self.max_cols))
        row = max(1, min(row, self.max_rows))

        if col != self.current_cols or row != self.current_rows:
            self.current_cols = col
            self.current_rows = row
            self.update()
            self.hoverChanged.emit(self.current_cols, self.current_rows)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.current_cols > 0 and self.current_rows > 0:
                self.selected.emit(self.current_cols, self.current_rows)


class GridSplitDialog(QDialog):
    """升目と QSpinBox が双方向に同期するダイアログ"""

    def __init__(self, parent=None, default_cols: int = 2, default_rows: int = 2):
        super().__init__(parent)
        self.setWindowTitle("xy分割")
        self.setFixedSize(260, 360)

        # 相互更新時の無限ループ防止フラグ
        self._is_updating = False

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 1. 升目ウィジェット（8×8マス）
        self.picker = GridPickerWidget(
            max_cols=8, max_rows=8, cell_size=24, spacing=4, parent=self
        )
        self.picker.set_grid(default_cols, default_rows)
        self.picker.hoverChanged.connect(self._on_picker_hover)
        self.picker.selected.connect(self._on_picker_click)

        # 中央揃えで配置
        h_picker_layout = QHBoxLayout()
        h_picker_layout.addStretch()
        h_picker_layout.addWidget(self.picker)
        h_picker_layout.addStretch()
        layout.addLayout(h_picker_layout)

        # 2. 数値入力欄 (QSpinBox)
        form_layout = QFormLayout()
        form_layout.setContentsMargins(15, 0, 15, 0)

        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 50)
        self.cols_spin.setValue(default_cols)
        self.cols_spin.valueChanged.connect(self._on_spin_changed)
        form_layout.addRow("横の分割数 (X):", self.cols_spin)

        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 50)
        self.rows_spin.setValue(default_rows)
        self.rows_spin.valueChanged.connect(self._on_spin_changed)
        form_layout.addRow("縦の分割数 (Y):", self.rows_spin)

        layout.addLayout(form_layout)

        # 3. ボタン (OK / キャンセル)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_picker_hover(self, cols: int, rows: int):
        """升目のホバー ➔ QSpinBox に反映"""
        if self._is_updating:
            return
        self._is_updating = True
        self.cols_spin.setValue(cols)
        self.rows_spin.setValue(rows)
        self._is_updating = False

    def _on_spin_changed(self):
        """QSpinBox の変更 ➔ 升目のハイライトに反映"""
        if self._is_updating:
            return
        self._is_updating = True
        self.picker.set_grid(self.cols_spin.value(), self.rows_spin.value())
        self._is_updating = False

    def _on_picker_click(self, cols: int, rows: int):
        """升目クリック時：値を確定して即座にダイアログを閉じる"""
        self.cols_spin.setValue(cols)
        self.rows_spin.setValue(rows)
        self.accept()

    def get_split_counts(self) -> tuple[int, int]:
        return self.cols_spin.value(), self.rows_spin.value()