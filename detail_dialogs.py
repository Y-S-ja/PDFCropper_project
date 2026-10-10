from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QFormLayout,
    QSpinBox,
    QDialogButtonBox,
)

class GridSplitDialog(QDialog):
    """縦横の分割数のみを入力するシンプルなダイアログ"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("xy分割")
        self.setFixedSize(220, 130)

        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        # 横の分割数 (列数 / X)
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 50)
        self.cols_spin.setValue(2)
        form_layout.addRow("横の分割数:", self.cols_spin)

        # 縦の分割数 (行数 / Y)
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 50)
        self.rows_spin.setValue(2)
        form_layout.addRow("縦の分割数:", self.rows_spin)

        layout.addLayout(form_layout)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_split_counts(self) -> tuple[int, int]:
        return self.cols_spin.value(), self.rows_spin.value()