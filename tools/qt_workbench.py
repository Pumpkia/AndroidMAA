"""Native Qt desktop workbench for MaaQQLogin."""

from __future__ import annotations
import os
from pathlib import Path
import subprocess
import sys
import threading
from datetime import datetime

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSlider, QSpinBox, QStackedWidget, QStyle, QTableWidget, QTableWidgetItem,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)
from job_model import JobDocument, JobStep, safe_name
from job_runner import MaaJobRunner


def app_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


APP_DIR = app_dir()
ASSETS_DIR = APP_DIR / "assets"
JOBS_DIR = APP_DIR / "jobs"
ADB_EXE = APP_DIR / "platform-tools" / "adb.exe"

RECOGNITION_OPTIONS = (("\u6a21\u677f\u5339\u914d", "TemplateMatch"), ("\u6587\u5b57\u8bc6\u522b (OCR)", "OCR"), ("\u76f4\u63a5\u547d\u4e2d", "DirectHit"))
ACTION_OPTIONS = (("\u70b9\u51fb", "Click"), ("\u8f93\u5165\u6587\u672c", "InputText"), ("\u6ed1\u52a8", "Swipe"), ("\u6309\u952e", "ClickKey"), ("\u7b49\u5f85", "DoNothing"))


def icon(widget, name):
    values = {
        "refresh": QStyle.StandardPixmap.SP_BrowserReload,
        "play": QStyle.StandardPixmap.SP_MediaPlay,
        "stop": QStyle.StandardPixmap.SP_MediaStop,
        "folder": QStyle.StandardPixmap.SP_DirIcon,
        "delete": QStyle.StandardPixmap.SP_TrashIcon,
        "up": QStyle.StandardPixmap.SP_ArrowUp,
        "down": QStyle.StandardPixmap.SP_ArrowDown,
        "device": QStyle.StandardPixmap.SP_ComputerIcon,
    }
    return widget.style().standardIcon(values[name])


class Worker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    def run(self):
        try:
            self.done.emit(self.operation())
        except Exception as error:
            self.failed.emit(str(error))


class AdbClient:
    def __init__(self):
        self.serial = ""

    def run(self, args, timeout=20):
        executable = ADB_EXE if ADB_EXE.exists() else Path("adb")
        return subprocess.run(
            [str(executable), *args], capture_output=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def devices(self):
        result = self.run(["devices"])
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", "replace") or "ADB 启动失败")
        return [line.split("\t", 1)[0] for line in result.stdout.decode().splitlines()[1:] if "\tdevice" in line]

    def args(self):
        return ["-s", self.serial] if self.serial else []

    def screenshot(self):
        result = self.run([*self.args(), "exec-out", "screencap", "-p"])
        image = cv2.imdecode(np.frombuffer(result.stdout, np.uint8), cv2.IMREAD_COLOR)
        if result.returncode or image is None:
            raise RuntimeError("无法从设备获取截图")
        return image

    def shell(self, args):
        result = self.run([*self.args(), "shell", *args])
        if result.returncode:
            raise RuntimeError(result.stderr.decode("utf-8", "replace") or "ADB 操作失败")

    def execute(self, step):
        if step.action == "Click" and step.target:
            self.shell(["input", "tap", *map(str, step.target)])
        elif step.action == "Swipe" and step.target and step.swipe_end:
            self.shell(["input", "swipe", *map(str, [*step.target, *step.swipe_end, step.duration])])
        elif step.action == "InputText":
            self.shell(["input", "text", step.input_text.replace(" ", "%s")])
        elif step.action == "ClickKey":
            self.shell(["input", "keyevent", str(step.key)])
        else:
            raise RuntimeError("当前步骤没有可预览的设备动作")


def to_pixmap(image):
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    h, w, channels = rgb.shape
    return QPixmap.fromImage(QImage(rgb.data, w, h, w * channels, QImage.Format.Format_RGB888).copy())


class PhonePreview(QWidget):
    def __init__(self):
        super().__init__()
        self.pixmap = None
        self.setMinimumWidth(310)

    def set_image(self, image):
        self.pixmap = to_pixmap(image)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#F6F7F9"))
        width = max(210, min(self.width() - 72, int((self.height() - 120) * .49)))
        height = int(width / .49)
        outer = QRect((self.width() - width) // 2, max(40, (self.height() - height) // 2), width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#202124"))
        painter.drawRoundedRect(outer, 42, 42)
        screen = outer.adjusted(13, 13, -13, -13)
        path = QPainterPath()
        path.addRoundedRect(screen, 33, 33)
        painter.save()
        painter.setClipPath(path)
        painter.fillRect(screen, QColor("#050505"))
        if self.pixmap:
            fitted = self.pixmap.scaled(screen.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(screen.center().x() - fitted.width() // 2, screen.center().y() - fitted.height() // 2, fitted)
        painter.restore()
        painter.setBrush(QColor("#202124"))
        painter.drawRoundedRect(QRect(outer.center().x() - 42, outer.top() + 13, 84, 24), 12, 12)
        if not self.pixmap:
            painter.setPen(QColor("#777B82"))
            painter.setFont(QFont("Microsoft YaHei UI", 10))
            painter.drawText(screen, Qt.AlignmentFlag.AlignCenter, "连接 ADB 设备并点击截图")


class Canvas(QWidget):
    changed = Signal(str, object)

    def __init__(self):
        super().__init__()
        self.pixmap = None
        self.source_size = QSize(720, 1600)
        self.mode = "roi"
        self.start = self.current = None
        self.roi = self.target = self.swipe_end = None
        self.setMinimumWidth(390)

    def set_image(self, image):
        self.pixmap = to_pixmap(image)
        self.source_size = QSize(image.shape[1], image.shape[0])
        self.update()

    def image_rect(self):
        source = self.pixmap.size() if self.pixmap else self.source_size
        size = source.scaled(QSize(max(220, self.width() - 96), max(340, self.height() - 110)), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect((self.width() - size.width()) // 2, (self.height() - size.height()) // 2, size.width(), size.height())

    def to_image(self, point):
        area = self.image_rect()
        if not area.contains(point):
            return None
        return [round((point.x() - area.x()) * self.source_size.width() / area.width()), round((point.y() - area.y()) * self.source_size.height() / area.height())]

    def to_canvas(self, point):
        area = self.image_rect()
        return QPoint(area.x() + round(point[0] * area.width() / self.source_size.width()), area.y() + round(point[1] * area.height() / self.source_size.height()))

    def clear_marks(self):
        self.roi = self.target = self.swipe_end = self.start = self.current = None
        self.update()

    def mousePressEvent(self, event):
        value = self.to_image(event.position().toPoint())
        if value:
            self.start = self.current = event.position().toPoint()
            if self.mode == "point":
                self.target = value
                self.changed.emit("target", value)
            self.update()

    def mouseMoveEvent(self, event):
        if self.start and self.mode != "point":
            self.current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if not self.start:
            return
        begin, end = self.to_image(self.start), self.to_image(event.position().toPoint())
        if begin and end and self.mode == "roi":
            x1, x2 = sorted((begin[0], end[0]))
            y1, y2 = sorted((begin[1], end[1]))
            self.roi = [x1, y1, max(1, x2 - x1), max(1, y2 - y1)]
            self.changed.emit("roi", self.roi)
        elif begin and end and self.mode == "swipe":
            self.target, self.swipe_end = begin, end
            self.changed.emit("swipe", [begin, end])
        self.start = self.current = None
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FBFCFD"))
        painter.setPen(QPen(QColor("#D8DEE6"), 1))
        for x in range(14, self.width(), 24):
            for y in range(14, self.height(), 24):
                painter.drawPoint(x, y)
        area = self.image_rect()
        painter.setBrush(QColor("#15171A"))
        painter.setPen(QPen(QColor("#CBD1D8"), 1))
        painter.drawRoundedRect(area.adjusted(-1, -1, 1, 1), 7, 7)
        if self.pixmap:
            fitted = self.pixmap.scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(area.center().x() - fitted.width() // 2, area.center().y() - fitted.height() // 2, fitted)
        else:
            painter.setPen(QColor("#9AA0A8"))
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "截图后在这里框选识别区域")
        painter.setPen(QPen(QColor("#21C55D"), 2, Qt.PenStyle.DashLine))
        if self.roi:
            painter.drawRect(QRect(self.to_canvas(self.roi[:2]), self.to_canvas([self.roi[0] + self.roi[2], self.roi[1] + self.roi[3]])).normalized())
        if self.start and self.current and self.mode == "roi":
            painter.drawRect(QRect(self.start, self.current).normalized())
        if self.target:
            point = self.to_canvas(self.target)
            painter.setPen(QPen(QColor("#FF9500"), 3))
            painter.drawEllipse(point, 9, 9)
            painter.drawLine(point + QPoint(-14, 0), point + QPoint(14, 0))
            painter.drawLine(point + QPoint(0, -14), point + QPoint(0, 14))
        if self.target and self.swipe_end:
            painter.setPen(QPen(QColor("#0A84FF"), 3))
            painter.drawLine(self.to_canvas(self.target), self.to_canvas(self.swipe_end))
        if self.start and self.current and self.mode == "swipe":
            painter.setPen(QPen(QColor("#0A84FF"), 3))
            painter.drawLine(self.start, self.current)


class DevicePane(QFrame):
    def __init__(self, app):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        header = QHBoxLayout()
        title = QLabel("设备预览")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        shot = QToolButton()
        shot.setIcon(icon(shot, "device"))
        shot.setToolTip("获取设备截图")
        shot.clicked.connect(app.capture_screen)
        header.addWidget(shot)
        layout.addLayout(header)
        self.phone = PhonePreview()
        layout.addWidget(self.phone, 1)


def tool(owner, icon_name, tip, callback):
    button = QToolButton()
    button.setIcon(icon(owner, icon_name))
    button.setToolTip(tip)
    button.clicked.connect(callback)
    return button

class RecordPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.device = DevicePane(app)
        self.device.setObjectName("devicePane")
        root.addWidget(self.device, 32)
        root.addWidget(self.build_canvas(), 37)
        root.addWidget(self.build_inspector(), 31)

    def build_canvas(self):
        pane = QFrame()
        pane.setObjectName("centerPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(16, 12, 16, 16)
        bar = QHBoxLayout()
        self.viewport = QLabel("视口：720 × 1600")
        self.viewport.setObjectName("muted")
        bar.addWidget(self.viewport)
        bar.addStretch()
        self.mode_buttons = {}
        for text, mode in (("框选识别区", "roi"), ("点击位置", "point"), ("滑动轨迹", "swipe")):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setProperty("toolMode", True)
            button.clicked.connect(lambda _checked=False, value=mode: self.set_mode(value))
            bar.addWidget(button)
            self.mode_buttons[mode] = button
        bar.addWidget(tool(self, "delete", "清除画布标记", self.clear_marks))
        layout.addLayout(bar)
        self.canvas = Canvas()
        self.canvas.changed.connect(self.selection_changed)
        layout.addWidget(self.canvas, 1)
        self.selection_info = QLabel("尚未选择识别区域或动作坐标")
        self.selection_info.setObjectName("selectionInfo")
        layout.addWidget(self.selection_info)
        self.set_mode("roi")
        return pane

    def build_inspector(self):
        pane = QFrame()
        pane.setObjectName("rightPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setContentsMargins(16, 10, 16, 4)
        title = QLabel("步骤列表")
        title.setObjectName("sectionTitle")
        bar.addWidget(title)
        bar.addStretch()
        for text, callback in (("新建", self.app.new_job), ("从用例库打开", self.app.open_job), ("保存到用例库", self.app.save_job), ("导出", self.app.export_pipeline)):
            button = QPushButton(text)
            button.setProperty("compact", True)
            button.clicked.connect(callback)
            bar.addWidget(button)
        layout.addLayout(bar)
        metadata = QFrame()
        metadata.setObjectName("metadataBar")
        grid = QGridLayout(metadata)
        grid.setContentsMargins(16, 8, 16, 8)
        grid.addWidget(QLabel("\u7528\u4f8b\u540d\u79f0"), 0, 0)
        self.case_name = QLineEdit(self.app.document.name)
        self.case_name.setPlaceholderText("\u8bf7\u8f93\u5165\u7528\u4f8b\u540d\u79f0")
        grid.addWidget(self.case_name, 0, 1)
        grid.addWidget(QLabel("\u5206\u7c7b"), 0, 2)
        self.case_category = QLineEdit(self.app.document.category)
        self.case_category.setPlaceholderText("\u9ed8\u8ba4")
        self.case_name.textEdited.connect(lambda _value: self.app.set_dirty(True))
        self.case_category.textEdited.connect(lambda _value: self.app.set_dirty(True))
        grid.addWidget(self.case_category, 0, 3)
        layout.addWidget(metadata)
        self.steps = QTableWidget(0, 4)
        self.steps.setHorizontalHeaderLabels(["#", "名称", "动作", "状态"])
        self.steps.verticalHeader().hide()
        self.steps.setShowGrid(False)
        self.steps.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for column, mode in ((0, QHeaderView.ResizeMode.ResizeToContents), (1, QHeaderView.ResizeMode.Stretch), (2, QHeaderView.ResizeMode.ResizeToContents), (3, QHeaderView.ResizeMode.ResizeToContents)):
            self.steps.horizontalHeader().setSectionResizeMode(column, mode)
        self.steps.itemSelectionChanged.connect(self.load_selected)
        layout.addWidget(self.steps, 36)
        title = QLabel("步骤属性")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        form = QFormLayout(host)
        form.setContentsMargins(18, 10, 18, 8)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        self.name = QLineEdit("步骤 1")
        self.recognition = QComboBox()
        for label, value in RECOGNITION_OPTIONS:
            self.recognition.addItem(label, value)
        self.action = QComboBox()
        for label, value in ACTION_OPTIONS:
            self.action.addItem(label, value)
        self.expected = QLineEdit()
        self.input_text = QLineEdit()
        self.threshold = QSlider(Qt.Orientation.Horizontal)
        self.threshold.setRange(0, 100)
        self.threshold.setValue(80)
        self.threshold_label = QLabel("0.80")
        self.threshold.valueChanged.connect(lambda value: self.threshold_label.setText(f"{value / 100:.2f}"))
        threshold_host = QWidget()
        threshold_layout = QHBoxLayout(threshold_host)
        threshold_layout.setContentsMargins(0, 0, 0, 0)
        threshold_layout.addWidget(self.threshold)
        threshold_layout.addWidget(self.threshold_label)
        self.key = QSpinBox()
        self.key.setRange(0, 999)
        self.key.setValue(4)
        self.duration = self.spin(300)
        self.pre_delay = self.spin(0)
        self.post_delay = self.spin(500)
        self.roi_info = QLabel("未框选")
        self.target_info = QLabel("未选择")
        for widget in (self.roi_info, self.target_info):
            widget.setObjectName("muted")
        fields = (
            ("名称", self.name), ("识别", self.recognition), ("动作", self.action),
            ("OCR 文字", self.expected), ("输入内容", self.input_text),
            ("匹配阈值", threshold_host), ("按键码", self.key),
            ("滑动时长", self.duration), ("执行前延迟", self.pre_delay),
            ("执行后延迟", self.post_delay), ("识别区域", self.roi_info),
            ("动作坐标", self.target_info),
        )
        for label, widget in fields:
            form.addRow(label, widget)
        scroll.setWidget(host)
        layout.addWidget(scroll, 48)
        actions = QGridLayout()
        actions.setContentsMargins(16, 8, 16, 12)
        add = QPushButton("添加步骤")
        add.setObjectName("primaryButton")
        add.clicked.connect(self.add_step)
        update = QPushButton("保存选中修改")
        update.clicked.connect(self.update_step)
        delete = QPushButton("删除")
        delete.setProperty("danger", True)
        delete.clicked.connect(self.delete_step)
        preview = QPushButton("在设备上预览此动作")
        preview.setObjectName("primaryButton")
        preview.setIcon(icon(preview, "play"))
        preview.clicked.connect(self.preview_step)
        buttons = (add, update, delete, tool(self, "up", "上移步骤", lambda: self.move_step(-1)), tool(self, "down", "下移步骤", lambda: self.move_step(1)))
        for column, button in enumerate(buttons):
            actions.addWidget(button, 0, column)
        actions.addWidget(preview, 1, 0, 1, 5)
        layout.addLayout(actions)
        return pane

    @staticmethod
    def spin(value):
        widget = QSpinBox()
        widget.setRange(0, 60000)
        widget.setValue(value)
        widget.setSuffix(" ms")
        return widget

    def set_mode(self, mode):
        self.canvas.mode = mode
        for key, button in self.mode_buttons.items():
            button.setChecked(key == mode)

    def clear_marks(self):
        self.canvas.clear_marks()
        self.roi_info.setText("未框选")
        self.target_info.setText("未选择")
        self.selection_info.setText("尚未选择识别区域或动作坐标")

    def selection_changed(self, kind, value):
        if kind == "roi":
            self.roi_info.setText(", ".join(map(str, value)))
            self.selection_info.setText(f"识别区域：x {value[0]}  y {value[1]}  w {value[2]}  h {value[3]}")
        elif kind == "target":
            self.target_info.setText(", ".join(map(str, value)))
            self.selection_info.setText(f"点击坐标：x {value[0]}  y {value[1]}")
        else:
            self.target_info.setText(f"{value[0]} → {value[1]}")
            self.selection_info.setText(f"滑动轨迹：{value[0]} → {value[1]}")

    def make_step(self, template=""):
        if self.recognition.currentData() == "TemplateMatch" and self.canvas.roi and self.app.screen_image is not None:
            x, y, width, height = self.canvas.roi
            crop = self.app.screen_image[y:y + height, x:x + width]
            relative = Path("jobs") / safe_name(self.app.document.name) / f"{safe_name(self.name.text(), 'step')}.png"
            output = ASSETS_DIR / "resource" / "image" / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            if crop.size and cv2.imwrite(str(output), crop):
                template = relative.as_posix()
        return JobStep(
            name=self.name.text().strip() or "新步骤",
            recognition=self.recognition.currentData(), action=self.action.currentData(),
            template=template, roi=self.canvas.roi, expected=self.expected.text(),
            threshold=self.threshold.value() / 100, target=self.canvas.target,
            swipe_end=self.canvas.swipe_end, input_text=self.input_text.text(),
            key=self.key.value(), duration=self.duration.value(),
            pre_delay=self.pre_delay.value(), post_delay=self.post_delay.value(),
        )

    def add_step(self):
        self.app.document.steps.append(self.make_step())
        self.refresh_steps(len(self.app.document.steps) - 1)
        self.name.setText(f"步骤 {len(self.app.document.steps) + 1}")
        self.app.set_dirty(True)

    def update_step(self):
        row = self.steps.currentRow()
        if row < 0:
            QMessageBox.information(self, "步骤属性", "请先选择需要修改的步骤。")
            return
        self.app.document.steps[row] = self.make_step(self.app.document.steps[row].template)
        self.refresh_steps(row)
        self.app.set_dirty(True)

    def delete_step(self):
        row = self.steps.currentRow()
        if row >= 0:
            self.app.document.steps.pop(row)
            self.refresh_steps(min(row, len(self.app.document.steps) - 1))
            self.app.set_dirty(True)

    def move_step(self, offset):
        row = self.steps.currentRow()
        target = row + offset
        if row >= 0 and 0 <= target < len(self.app.document.steps):
            self.app.document.steps[row], self.app.document.steps[target] = self.app.document.steps[target], self.app.document.steps[row]
            self.refresh_steps(target)
            self.app.set_dirty(True)

    def refresh_steps(self, select=-1):
        names = {"Click": "点击", "InputText": "输入", "Swipe": "滑动", "ClickKey": "按键", "DoNothing": "等待"}
        self.steps.blockSignals(True)
        self.steps.setRowCount(len(self.app.document.steps))
        for row, step in enumerate(self.app.document.steps):
            for column, value in enumerate((f"{row + 1:02d}", step.name, names.get(step.action, step.action), "就绪")):
                self.steps.setItem(row, column, QTableWidgetItem(value))
        self.steps.blockSignals(False)
        if 0 <= select < self.steps.rowCount():
            self.steps.selectRow(select)

    def load_selected(self):
        row = self.steps.currentRow()
        if not 0 <= row < len(self.app.document.steps):
            return
        step = self.app.document.steps[row]
        self.name.setText(step.name)
        self.recognition.setCurrentIndex(max(0, self.recognition.findData(step.recognition)))
        self.action.setCurrentIndex(max(0, self.action.findData(step.action)))
        self.expected.setText(step.expected)
        self.input_text.setText(step.input_text)
        self.threshold.setValue(round(step.threshold * 100))
        self.key.setValue(step.key)
        self.duration.setValue(step.duration)
        self.pre_delay.setValue(step.pre_delay)
        self.post_delay.setValue(step.post_delay)
        self.canvas.roi, self.canvas.target, self.canvas.swipe_end = step.roi, step.target, step.swipe_end
        self.roi_info.setText(str(step.roi) if step.roi else "未框选")
        self.target_info.setText(str(step.target) if step.target else "未选择")
        self.canvas.update()

    def preview_step(self):
        row = self.steps.currentRow()
        step = self.app.document.steps[row] if 0 <= row < len(self.app.document.steps) else self.make_step()
        self.app.run_async(lambda: self.app.adb.execute(step), lambda _value: self.app.toast(f"已在设备上执行：{step.name}"))

class PlaybackPage(QWidget):
    log_signal = Signal(str)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.queue = []
        self.runner = MaaJobRunner(APP_DIR, ASSETS_DIR, JOBS_DIR)
        self.stop_requested = False
        self.log_signal.connect(self.append_log)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.device = DevicePane(app)
        self.device.setObjectName("devicePane")
        root.addWidget(self.device, 38)
        root.addWidget(self.build_library(), 15)
        root.addWidget(self.build_queue(), 23)
        root.addWidget(self.build_controls(), 24)

    def build_library(self):
        pane = QFrame()
        pane.setObjectName("centerPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(16, 14, 16, 14)
        header = QHBoxLayout()
        title = QLabel("用例库")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(tool(self, "refresh", "刷新用例库", self.refresh_library))
        layout.addLayout(header)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索用例...")
        self.search.textChanged.connect(self.refresh_library)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(lambda *_args: self.add_selected())
        layout.addWidget(self.tree, 1)
        library_actions = QHBoxLayout()
        create = QPushButton("\u65b0\u5efa\u7528\u4f8b")
        create.clicked.connect(self.new_case)
        edit = QPushButton("\u7f16\u8f91")
        edit.clicked.connect(self.edit_selected)
        delete = QPushButton("\u5220\u9664")
        delete.setProperty("danger", True)
        delete.clicked.connect(self.delete_selected)
        library_actions.addWidget(create)
        library_actions.addWidget(edit)
        library_actions.addWidget(delete)
        layout.addLayout(library_actions)
        add = QPushButton("\u6dfb\u52a0\u5230\u6267\u884c\u961f\u5217")
        add.setObjectName("primaryButton")
        add.clicked.connect(self.add_selected)
        layout.addWidget(add)
        return pane

    def build_queue(self):
        pane = QFrame()
        pane.setObjectName("centerPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.setContentsMargins(18, 12, 18, 12)
        title = QLabel("执行控制")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        self.state = QLabel("就绪")
        self.state.setObjectName("successPill")
        header.addWidget(self.state)
        layout.addLayout(header)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        layout.addWidget(self.progress)
        title = QLabel("执行队列")
        title.setObjectName("propertyTitle")
        layout.addWidget(title)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "用例名称", "分类", "状态"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for column, mode in ((0, QHeaderView.ResizeMode.ResizeToContents), (1, QHeaderView.ResizeMode.Stretch), (2, QHeaderView.ResizeMode.ResizeToContents), (3, QHeaderView.ResizeMode.ResizeToContents)):
            self.table.horizontalHeader().setSectionResizeMode(column, mode)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        row.setContentsMargins(16, 8, 16, 12)
        remove = QPushButton("移除")
        remove.clicked.connect(self.remove_selected)
        clear = QPushButton("清空")
        clear.clicked.connect(self.clear_queue)
        row.addWidget(remove)
        row.addWidget(clear)
        row.addStretch()
        row.addWidget(tool(self, "up", "队列上移", lambda: self.move_queue(-1)))
        row.addWidget(tool(self, "down", "队列下移", lambda: self.move_queue(1)))
        layout.addLayout(row)
        return pane

    def build_controls(self):
        pane = QFrame()
        pane.setObjectName("rightPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(20, 18, 20, 16)
        actions = QHBoxLayout()
        self.start = QPushButton("开始执行")
        self.start.setObjectName("largePrimary")
        self.start.setIcon(icon(self.start, "play"))
        self.start.clicked.connect(self.start_execution)
        self.stop = QPushButton("停止执行")
        self.stop.setObjectName("largeSecondary")
        self.stop.setIcon(icon(self.stop, "stop"))
        self.stop.clicked.connect(self.stop_execution)
        self.stop.setEnabled(False)
        actions.addWidget(self.start)
        actions.addWidget(self.stop)
        layout.addLayout(actions)
        title = QLabel("快速设置")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.retry = QCheckBox("失败自动重试")
        self.retry.setChecked(True)
        self.capture_error = QCheckBox("捕获错误")
        for checkbox in (self.retry, self.capture_error):
            frame = QFrame()
            frame.setObjectName("settingRow")
            row = QHBoxLayout(frame)
            row.addWidget(checkbox)
            layout.addWidget(frame)
        header = QHBoxLayout()
        title = QLabel("执行日志")
        title.setObjectName("sectionTitle")
        header.addWidget(title)
        header.addStretch()
        clear = QPushButton("清空")
        clear.setProperty("link", True)
        clear.clicked.connect(lambda: self.log.clear())
        header.addWidget(clear)
        layout.addLayout(header)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("logView")
        layout.addWidget(self.log, 1)
        return pane

    def refresh_library(self):
        query = self.search.text().strip().casefold() if hasattr(self, "search") else ""
        self.tree.clear()
        categories = {}
        for path in sorted(JOBS_DIR.rglob("*.maa_job.json")):
            try:
                document = JobDocument.load(path)
            except Exception:
                continue
            if query and query not in document.name.casefold():
                continue
            category = document.category or "默认"
            if category not in categories:
                parent = QTreeWidgetItem([category])
                parent.setIcon(0, icon(self, "folder"))
                self.tree.addTopLevelItem(parent)
                categories[category] = parent
            item = QTreeWidgetItem([document.name])
            item.setData(0, Qt.ItemDataRole.UserRole, str(path))
            categories[category].addChild(item)
            categories[category].setExpanded(True)

    def selected_library_path(self):
        item = self.tree.currentItem()
        value = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        return Path(value) if value else None

    def new_case(self):
        self.app.new_job()
        self.app.switch_page(0)

    def edit_selected(self):
        path = self.selected_library_path()
        if not path:
            QMessageBox.information(self, "\u7528\u4f8b\u5e93", "\u8bf7\u5148\u9009\u62e9\u9700\u8981\u7f16\u8f91\u7684\u7528\u4f8b\u3002")
            return
        self.app.load_job(path)
        self.app.switch_page(0)

    def delete_selected(self):
        path = self.selected_library_path()
        if not path:
            QMessageBox.information(self, "\u7528\u4f8b\u5e93", "\u8bf7\u5148\u9009\u62e9\u9700\u8981\u5220\u9664\u7684\u7528\u4f8b\u3002")
            return
        answer = QMessageBox.question(self, "\u5220\u9664\u7528\u4f8b", f"\u786e\u5b9a\u4ece\u7528\u4f8b\u5e93\u5220\u9664 {path.stem.replace('.maa_job', '')} \u5417\uff1f")
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            path.unlink()
            self.queue = [item for item in self.queue if item.resolve() != path.resolve()]
            self.refresh_queue()
            self.refresh_library()
            self.app.toast("\u7528\u4f8b\u5df2\u4ece\u7528\u4f8b\u5e93\u5220\u9664")
        except Exception as error:
            QMessageBox.critical(self, "\u5220\u9664\u5931\u8d25", str(error))

    def add_selected(self):
        path = self.selected_library_path()
        if path:
            self.queue.append(path)
            self.refresh_queue(len(self.queue) - 1)

    def refresh_queue(self, select=-1):
        self.table.setRowCount(len(self.queue))
        for row, path in enumerate(self.queue):
            try:
                document = JobDocument.load(path)
            except Exception:
                document = JobDocument(name=path.stem, category="-")
            for column, value in enumerate((f"{row + 1:02d}", document.name, document.category, "等待中")):
                self.table.setItem(row, column, QTableWidgetItem(value))
        if 0 <= select < len(self.queue):
            self.table.selectRow(select)

    def remove_selected(self):
        row = self.table.currentRow()
        if row >= 0:
            self.queue.pop(row)
            self.refresh_queue(min(row, len(self.queue) - 1))

    def clear_queue(self):
        self.queue.clear()
        self.refresh_queue()

    def move_queue(self, offset):
        row = self.table.currentRow()
        target = row + offset
        if row >= 0 and 0 <= target < len(self.queue):
            self.queue[row], self.queue[target] = self.queue[target], self.queue[row]
            self.refresh_queue(target)

    def append_log(self, message):
        self.log.appendPlainText(f"[{datetime.now():%H:%M:%S}] {message}")

    def start_execution(self):
        if not self.queue:
            QMessageBox.information(self, "执行队列", "请先从用例库添加用例。")
            return
        if not self.app.adb.serial:
            QMessageBox.warning(self, "ADB 设备", "请先选择已连接的 ADB 设备。")
            return
        self.stop_requested = False
        self.start.setEnabled(False)
        self.stop.setEnabled(True)
        self.state.setText("执行中")
        self.progress.setValue(1)
        queue, serial = list(self.queue), self.app.adb.serial

        def operation():
            succeeded = 0
            for index, path in enumerate(queue):
                if self.stop_requested:
                    break
                self.log_signal.emit(f"开始用例：{path.name}")
                ok = self.runner.run(JobDocument.load(path), serial, self.log_signal.emit)
                succeeded += int(ok)
                self.log_signal.emit("用例完成" if ok else "用例失败")
                value = round((index + 1) / len(queue) * 100)
                self.app.call_ui(lambda current=value: self.progress.setValue(current))
            return succeeded

        worker = Worker(operation)
        worker.done.connect(self.execution_finished)
        worker.failed.connect(self.execution_failed)
        self.app.keep_worker(worker)
        worker.start()

    def stop_execution(self):
        self.stop_requested = True
        self.stop.setEnabled(False)
        threading.Thread(target=lambda: self.runner.stop(self.log_signal.emit), daemon=True).start()

    def execution_finished(self, count):
        self.start.setEnabled(True)
        self.stop.setEnabled(False)
        self.state.setText("已停止" if self.stop_requested else "已完成")
        self.append_log(f"执行结束：成功 {count} / {len(self.queue)}")

    def execution_failed(self, error):
        self.start.setEnabled(True)
        self.stop.setEnabled(False)
        self.state.setText("失败")
        self.append_log(f"执行失败：{error}")


class Workbench(QMainWindow):
    ui_call = Signal(object)

    def __init__(self):
        super().__init__()
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        self.adb = AdbClient()
        self.document = JobDocument(name="新用例", category="默认")
        self.current_path = None
        self.screen_image = None
        self.workers = []
        self.dirty = False
        self.ui_call.connect(lambda callback: callback())
        self.resize(1600, 930)
        self.setMinimumSize(1280, 760)
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.build_topbar())
        self.pages = QStackedWidget()
        self.record = RecordPage(self)
        self.playback = PlaybackPage(self)
        self.pages.addWidget(self.record)
        self.pages.addWidget(self.playback)
        root.addWidget(self.pages, 1)
        root.addWidget(self.build_statusbar())
        self.setCentralWidget(central)
        self.apply_style()
        self.refresh_devices()
        self.playback.refresh_library()
        self.update_title()

    def build_topbar(self):
        bar = QFrame()
        bar.setObjectName("topBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 10, 18, 10)
        mark = QLabel("M")
        mark.setObjectName("brandMark")
        layout.addWidget(mark)
        brand = QLabel("MaaQQLogin")
        brand.setObjectName("brand")
        layout.addWidget(brand)
        layout.addSpacing(24)
        self.record_button = QPushButton("用例录制")
        self.record_button.setCheckable(True)
        self.record_button.setProperty("modeButton", True)
        self.record_button.clicked.connect(lambda: self.switch_page(0))
        layout.addWidget(self.record_button)
        self.play_button = QPushButton("用例回放")
        self.play_button.setCheckable(True)
        self.play_button.setProperty("modeButton", True)
        self.play_button.clicked.connect(lambda: self.switch_page(1))
        layout.addWidget(self.play_button)
        layout.addStretch()
        label = QLabel("ADB 设备")
        label.setObjectName("muted")
        layout.addWidget(label)
        self.devices = QComboBox()
        self.devices.setMinimumWidth(220)
        self.devices.currentTextChanged.connect(self.device_changed)
        layout.addWidget(self.devices)
        layout.addWidget(tool(self, "refresh", "刷新 ADB 设备", self.refresh_devices))
        screenshot = QPushButton("截图")
        screenshot.setObjectName("primaryButton")
        screenshot.clicked.connect(self.capture_screen)
        layout.addWidget(screenshot)
        self.record_button.setChecked(True)
        return bar

    def build_statusbar(self):
        bar = QFrame()
        bar.setObjectName("bottomBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 6, 20, 6)
        self.adb_status = QLabel("●  ADB：未连接")
        layout.addWidget(self.adb_status)
        layout.addSpacing(18)
        coordinates = QLabel("坐标：--")
        coordinates.setObjectName("muted")
        layout.addWidget(coordinates)
        layout.addStretch()
        self.message_status = QLabel("系统就绪")
        self.message_status.setObjectName("muted")
        layout.addWidget(self.message_status)
        return bar
    def apply_style(self):
        self.setStyleSheet("""
        * { font-family: 'Microsoft YaHei UI'; font-size: 13px; color: #24272C; }
        QMainWindow, QWidget { background: #FFFFFF; }
        #topBar { border-bottom: 1px solid #E4E7EB; min-height: 50px; }
        #bottomBar { border-top: 1px solid #E4E7EB; min-height: 28px; }
        #devicePane { background: #F6F7F9; border-right: 1px solid #E4E7EB; }
        #centerPane { background: #FFFFFF; border-right: 1px solid #E4E7EB; }
        #rightPane { background: #FAFAFB; }\n        #metadataBar { background: #FAFAFB; border-bottom: 1px solid #E4E7EB; }
        #brand { font-size: 19px; font-weight: 700; }
        #brandMark { background: #0A84FF; color: white; font-size: 16px; font-weight: 700;
                     border-radius: 5px; min-width: 28px; min-height: 28px;
                     qproperty-alignment: AlignCenter; }
        #sectionTitle { font-size: 14px; font-weight: 650; color: #474B52; }
        #propertyTitle { padding: 12px 18px; background: #F5F6F8;
                         border-top: 1px solid #E4E7EB; border-bottom: 1px solid #E4E7EB;
                         font-weight: 650; }
        #muted { color: #858B94; }
        #selectionInfo { background: white; border: 1px solid #E0E4E9;
                         border-radius: 6px; padding: 9px 12px; color: #66707A; }
        QPushButton, QToolButton { background: #FFFFFF; border: 1px solid #DDE1E6;
                                  border-radius: 6px; padding: 7px 13px; min-height: 18px; }
        QPushButton:hover, QToolButton:hover { background: #F2F7FF; border-color: #8CC4FF; }
        QPushButton:pressed, QToolButton:pressed { background: #E5F1FF; }
        QPushButton:disabled, QToolButton:disabled { color: #B8BDC5; background: #F2F3F5; border-color: #E7E9EC; }
        QPushButton[compact='true'] { padding: 5px 9px; }
        QPushButton[modeButton='true'] { background: #F2F3F5; border-color: transparent; font-weight: 600; padding: 8px 18px; }
        QPushButton[modeButton='true']:checked { background: #FFFFFF; border-color: #DDE1E6; }
        QPushButton[toolMode='true'] { padding: 6px 10px; color: #69717B; }
        QPushButton[toolMode='true']:checked { color: #0A84FF; background: #EAF4FF; border-color: #B9DCFF; }
        #primaryButton, #largePrimary { background: #0A84FF; color: #FFFFFF; border-color: #0A84FF; font-weight: 650; }
        #primaryButton:hover, #largePrimary:hover { background: #0075E8; }
        #largePrimary, #largeSecondary { min-height: 84px; font-size: 15px; }
        QPushButton[danger='true'] { color: #E5484D; background: #FFF5F5; border-color: #FFD6D8; }
        QPushButton[link='true'] { color: #0A84FF; border: none; background: transparent; padding: 4px; }
        QLineEdit, QComboBox, QSpinBox { background: #FFFFFF; border: 1px solid #DDE1E6; border-radius: 6px; padding: 7px 9px; min-height: 20px; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #0A84FF; }
        QTableWidget, QTreeWidget, QPlainTextEdit { border: none; background: #FFFFFF; outline: none; selection-background-color: #E4F1FF; selection-color: #0969C8; }
        QHeaderView::section { background: #F3F4F6; color: #747A83; border: none; border-bottom: 1px solid #E4E7EB; padding: 9px 8px; font-weight: 600; }
        QTableWidget::item { padding: 8px; border-bottom: 1px solid #EFF1F3; }
        QTreeWidget::item { min-height: 34px; }
        #settingRow { background: #FFFFFF; border: 1px solid #E4E7EB; border-radius: 7px; min-height: 46px; }
        #logView { background: #F7F8FA; border-top: 1px solid #E4E7EB; color: #60666E; padding: 10px; }
        #successPill { background: #E7F8EC; color: #249B4A; border-radius: 12px; padding: 4px 12px; font-weight: 650; }
        QProgressBar { border: none; background: #EEF0F2; }
        QProgressBar::chunk { background: #0A84FF; }
        QScrollBar:vertical { background: transparent; width: 10px; }
        QScrollBar::handle:vertical { background: #C9CDD3; min-height: 32px; border-radius: 5px; margin: 2px; }
        QSlider::groove:horizontal { height: 5px; background: #DFE3E7; border-radius: 2px; }
        QSlider::handle:horizontal { width: 15px; margin: -5px 0; border-radius: 7px; background: #0A84FF; }
        """)

    def switch_page(self, index):
        self.pages.setCurrentIndex(index)
        self.record_button.setChecked(index == 0)
        self.play_button.setChecked(index == 1)
        if index:
            self.playback.refresh_library()

    def keep_worker(self, worker):
        self.workers.append(worker)
        worker.finished.connect(lambda: self.workers.remove(worker) if worker in self.workers else None)

    def run_async(self, operation, done=None):
        worker = Worker(operation)
        self.keep_worker(worker)
        if done:
            worker.done.connect(done)
        worker.failed.connect(lambda error: QMessageBox.critical(self, "操作失败", error))
        worker.start()

    def call_ui(self, callback):
        self.ui_call.emit(callback)

    def refresh_devices(self):
        self.message_status.setText("正在刷新 ADB 设备...")

        def done(devices):
            current = self.devices.currentText()
            self.devices.blockSignals(True)
            self.devices.clear()
            self.devices.addItems(devices)
            self.devices.blockSignals(False)
            self.devices.setCurrentText(current if current in devices else (devices[0] if devices else ""))
            self.device_changed(self.devices.currentText())
            self.message_status.setText("设备列表已刷新")

        self.run_async(self.adb.devices, done)

    def device_changed(self, serial):
        self.adb.serial = serial
        connected = bool(serial)
        self.adb_status.setText(f"●  ADB：{'已连接' if connected else '未连接'}")
        self.adb_status.setStyleSheet(f"color: {'#22B455' if connected else '#A0A5AD'}")

    def capture_screen(self):
        if not self.adb.serial:
            QMessageBox.warning(self, "ADB 设备", "未检测到可用设备，请连接设备并刷新。")
            return
        self.message_status.setText("正在获取设备截图...")

        def done(image):
            self.screen_image = image
            self.record.canvas.set_image(image)
            self.record.device.phone.set_image(image)
            self.playback.device.phone.set_image(image)
            self.document.device_size = [image.shape[1], image.shape[0]]
            self.record.viewport.setText(f"视口：{image.shape[1]} × {image.shape[0]}")
            self.message_status.setText("截图完成")

        self.run_async(self.adb.screenshot, done)

    def new_job(self):
        if self.dirty and QMessageBox.question(self, "\u65b0\u5efa\u7528\u4f8b", "\u5f53\u524d\u4fee\u6539\u5c1a\u672a\u4fdd\u5b58\uff0c\u4ecd\u8981\u65b0\u5efa\u5417\uff1f") != QMessageBox.StandardButton.Yes:
            return
        self.document = JobDocument(name="\u65b0\u7528\u4f8b", category="\u9ed8\u8ba4")
        self.current_path = None
        self.record.case_name.setText(self.document.name)
        self.record.case_category.setText(self.document.category)
        self.record.refresh_steps()
        self.record.clear_marks()
        self.set_dirty(False)

    def open_job(self):
        value, _filter = QFileDialog.getOpenFileName(self, "\u4ece\u7528\u4f8b\u5e93\u6253\u5f00", str(JOBS_DIR), "\u7528\u4f8b\u6587\u4ef6 (*.maa_job.json)")
        if value:
            self.load_job(Path(value))

    def load_job(self, path):
        try:
            self.document = JobDocument.load(Path(path))
            self.current_path = Path(path)
            self.record.case_name.setText(self.document.name)
            self.record.case_category.setText(self.document.category)
            self.record.refresh_steps(0)
            self.set_dirty(False)
        except Exception as error:
            QMessageBox.critical(self, "\u6253\u5f00\u5931\u8d25", str(error))

    def save_job(self):
        name = self.record.case_name.text().strip()
        category = self.record.case_category.text().strip() or "\u9ed8\u8ba4"
        if not name:
            QMessageBox.warning(self, "\u4fdd\u5b58\u7528\u4f8b", "\u8bf7\u5148\u586b\u5199\u7528\u4f8b\u540d\u79f0\u3002")
            self.record.case_name.setFocus()
            return
        self.document.name = name
        self.document.category = category
        path = self.current_path
        if path is None:
            path = JOBS_DIR / safe_name(category, "\u9ed8\u8ba4") / f"{safe_name(name, 'case')}.maa_job.json"
        try:
            self.document.save(path)
            self.current_path = path
            self.set_dirty(False)
            self.playback.refresh_library()
            self.toast("\u5df2\u4fdd\u5b58\u5230\u7528\u4f8b\u5e93")
            QMessageBox.information(self, "\u4fdd\u5b58\u6210\u529f", "\u5df2\u4fdd\u5b58\u5230\u7528\u4f8b\u5e93\u3002")
        except Exception as error:
            QMessageBox.critical(self, "\u4fdd\u5b58\u5931\u8d25", str(error))

    def export_pipeline(self):
        default = ASSETS_DIR / "resource" / "pipeline" / f"{safe_name(self.document.name)}.json"
        value, _filter = QFileDialog.getSaveFileName(self, "导出 Pipeline", str(default), "JSON (*.json)")
        if value:
            try:
                self.document.export_pipeline(Path(value), JOBS_DIR)
                self.toast("Pipeline 已导出")
            except Exception as error:
                QMessageBox.critical(self, "导出失败", str(error))

    def set_dirty(self, dirty):
        self.dirty = dirty
        self.update_title()

    def update_title(self):
        self.setWindowTitle(f"MaaQQLogin - 自动化用例工作台{' *' if self.dirty else ''}")

    def toast(self, message):
        self.message_status.setText(message)

    def closeEvent(self, event):
        if self.dirty and QMessageBox.question(self, "退出", "当前修改尚未保存，确认退出吗？") != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        if self.playback.runner.running:
            self.playback.stop_execution()
        event.accept()


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    application = QApplication(sys.argv)
    application.setApplicationName("MaaQQLogin")
    application.setStyle("Fusion")
    window = Workbench()
    window.show()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()