"""Visual job editor for building MaaFramework pipelines from an ADB screen."""

from __future__ import annotations

import base64
from pathlib import Path
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import cv2
import numpy as np

from job_model import SMART_CATEGORIES, JobDocument, JobStep, safe_name, suggest_category


PROJECT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
ASSETS_DIR = PROJECT_DIR / "assets"
IMAGE_DIR = ASSETS_DIR / "resource" / "image" / "jobs"
PIPELINE_DIR = ASSETS_DIR / "resource" / "pipeline"
JOBS_DIR = PROJECT_DIR / "jobs"
ADB_TIMEOUT = 20
RECOGNITION_LABELS = {
    "模板匹配（找图）": "TemplateMatch",
    "文字识别（OCR）": "OCR",
    "直接执行（无需识别）": "DirectHit",
}
ACTION_LABELS = {
    "点击": "Click",
    "滑动": "Swipe",
    "输入文本": "InputText",
    "按键": "ClickKey",
    "等待 / 无动作": "DoNothing",
}
RECOGNITION_NAMES = {value: key for key, value in RECOGNITION_LABELS.items()}
ACTION_NAMES = {value: key for key, value in ACTION_LABELS.items()}


class AdbClient:
    def __init__(self) -> None:
        self.serial = ""
        self.coordinate_scale = (1.0, 1.0)
        bundled_adb = PROJECT_DIR / "platform-tools" / "adb.exe"
        self.executable = str(bundled_adb) if bundled_adb.exists() else "adb"

    def _run(self, arguments: list[str], timeout: int = ADB_TIMEOUT) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                [self.executable, *arguments],
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as error:
            raise RuntimeError("找不到 adb，请先将 Android platform-tools 加入 PATH") from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("ADB 操作超时") from error

    def devices(self) -> list[str]:
        result = self._run(["devices", "-l"])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
        devices: list[str] = []
        for line in result.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    def _device_args(self) -> list[str]:
        if not self.serial:
            raise RuntimeError("请先选择 ADB 设备")
        return ["-s", self.serial]

    def screenshot(self) -> np.ndarray:
        result = self._run([*self._device_args(), "exec-out", "screencap", "-p"])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or "截图失败")
        image = cv2.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError("ADB 返回的截图不是有效图片")
        height, width = image.shape[:2]
        scale = 720 / min(width, height)
        normalized_width = round(width * scale)
        normalized_height = round(height * scale)
        self.coordinate_scale = (width / normalized_width, height / normalized_height)
        normalized = cv2.resize(
            image,
            (normalized_width, normalized_height),
            interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
        )
        return normalized

    def tap(self, point: list[int]) -> None:
        x, y = self._physical_point(point)
        self._shell(["input", "tap", str(x), str(y)])

    def swipe(self, start: list[int], end: list[int], duration: int) -> None:
        start_x, start_y = self._physical_point(start)
        end_x, end_y = self._physical_point(end)
        self._shell(
            [
                "input",
                "swipe",
                str(start_x),
                str(start_y),
                str(end_x),
                str(end_y),
                str(duration),
            ]
        )

    def input_text(self, value: str) -> None:
        self._shell(["input", "text", value.replace(" ", "%s")])

    def keyevent(self, key: int) -> None:
        self._shell(["input", "keyevent", str(key)])

    def _physical_point(self, point: list[int]) -> tuple[int, int]:
        if len(point) != 2:
            raise RuntimeError("动作坐标无效")
        scale_x, scale_y = self.coordinate_scale
        return round(point[0] * scale_x), round(point[1] * scale_y)

    def _shell(self, arguments: list[str]) -> None:
        result = self._run([*self._device_args(), "shell", *arguments])
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip() or "ADB 操作失败")


class JobEditor(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("QQ App 作业编辑器")
        self.geometry("1460x900")
        self.minsize(1200, 760)

        self.adb = AdbClient()
        self.document = JobDocument()
        self.current_path: Path | None = None
        self.current_image: np.ndarray | None = None
        self.photo: tk.PhotoImage | None = None
        self.display_scale = 1.0
        self.display_origin = (0, 0)
        self.drag_start: tuple[int, int] | None = None
        self.selection_roi: list[int] | None = None
        self.selection_target: list[int] | None = None
        self.selection_swipe_end: list[int] | None = None
        self.dirty = False
        self.job_paths: dict[str, Path] = {}

        self._create_variables()
        self._configure_style()
        self._build_ui()
        self._bind_events()
        self.refresh_jobs()
        self.refresh_devices()
        self.refresh_steps()

    def _create_variables(self) -> None:
        self.device_var = tk.StringVar()
        self.job_name_var = tk.StringVar(value=self.document.name)
        self.category_var = tk.StringVar(value=self.document.category)
        self.status_var = tk.StringVar(value="连接设备并获取截图后开始编排")
        self.mode_var = tk.StringVar(value="template")
        self.step_name_var = tk.StringVar(value="步骤 1")
        self.recognition_var = tk.StringVar(value="模板匹配（找图）")
        self.action_var = tk.StringVar(value="点击")
        self.expected_var = tk.StringVar()
        self.threshold_var = tk.StringVar(value="0.80")
        self.input_var = tk.StringVar()
        self.key_var = tk.StringVar(value="4")
        self.duration_var = tk.StringVar(value="300")
        self.pre_delay_var = tk.StringVar(value="0")
        self.delay_var = tk.StringVar(value="500")
        self.roi_var = tk.StringVar(value="未框选")
        self.target_var = tk.StringVar(value="未选择")
        self.search_var = tk.StringVar()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 13, "bold"))
        style.configure("Section.TLabel", font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 9, "bold"))

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self, padding=(12, 10))
        toolbar.pack(fill=tk.X)
        ttk.Label(toolbar, text="QQ App 用例录制器", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(toolbar, text="截图识别与步骤编排", foreground="#5f6b7a").pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(toolbar, text="作业执行", command=self.open_runner, style="Accent.TButton", width=10).pack(side=tk.RIGHT)
        ttk.Button(toolbar, text="导出 Pipeline", command=self.export_pipeline, width=13).pack(side=tk.RIGHT, padx=6)
        ttk.Button(toolbar, text="另存为", command=lambda: self.save_job(save_as=True), width=8).pack(side=tk.RIGHT, padx=6)
        ttk.Button(toolbar, text="保存", command=self.save_job, style="Accent.TButton", width=8).pack(side=tk.RIGHT)
        ttk.Button(toolbar, text="新建", command=self.new_job, width=8).pack(side=tk.RIGHT, padx=6)

        context_bar = ttk.Frame(self, padding=(12, 0, 12, 10))
        context_bar.pack(fill=tk.X)
        ttk.Label(context_bar, text="设备").pack(side=tk.LEFT)
        self.device_combo = ttk.Combobox(context_bar, textvariable=self.device_var, width=22, state="readonly")
        self.device_combo.pack(side=tk.LEFT, padx=(6, 4))
        ttk.Button(context_bar, text="刷新设备", command=self.refresh_devices, width=9).pack(side=tk.LEFT)
        ttk.Button(context_bar, text="获取截图", command=self.capture_screen, width=9).pack(side=tk.LEFT, padx=(6, 18))
        ttk.Label(context_bar, text="当前作业").pack(side=tk.LEFT)
        ttk.Entry(context_bar, textvariable=self.job_name_var, width=28).pack(side=tk.LEFT, padx=6)

        body = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))
        preview_frame = ttk.Frame(body, padding=(0, 0, 10, 0))
        editor_frame = ttk.Frame(body, width=500)
        body.add(preview_frame, weight=3)
        body.add(editor_frame, weight=2)

        mode_bar = ttk.Frame(preview_frame)
        mode_bar.pack(fill=tk.X, pady=(0, 7))
        ttk.Label(mode_bar, text="截图画布", style="Section.TLabel").pack(side=tk.LEFT)
        for label, value in (("框选模板", "template"), ("选择点击点", "point"), ("绘制滑动", "swipe")):
            ttk.Radiobutton(mode_bar, text=label, value=value, variable=self.mode_var).pack(side=tk.LEFT, padx=(14, 0))
        ttk.Button(mode_bar, text="清除标记", command=self.clear_selection, width=10).pack(side=tk.RIGHT)

        canvas_frame = ttk.Frame(preview_frame, relief=tk.SUNKEN, borderwidth=1)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(canvas_frame, background="#17191c", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        notebook = ttk.Notebook(editor_frame)
        notebook.pack(fill=tk.BOTH, expand=True)
        steps_page = ttk.Frame(notebook, padding=10)
        library_page = ttk.Frame(notebook, padding=10)
        notebook.add(steps_page, text="步骤编排")
        notebook.add(library_page, text="作业库")
        self._build_steps_page(steps_page)
        self._build_library_page(library_page)

        status = ttk.Frame(self, padding=(12, 4, 12, 9))
        status.pack(fill=tk.X)
        ttk.Separator(status).pack(fill=tk.X, pady=(0, 7))
        ttk.Label(status, textvariable=self.status_var).pack(side=tk.LEFT)
        ttk.Label(status, text="Maa 坐标：短边 720").pack(side=tk.RIGHT)
    def _build_steps_page(self, parent: ttk.Frame) -> None:
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("index", "name", "recognition", "action")
        self.steps_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=8, selectmode="browse")
        headings = (("index", "#", 36), ("name", "步骤", 145), ("recognition", "识别", 100), ("action", "动作", 80))
        for key, title, width in headings:
            self.steps_tree.heading(key, text=title)
            self.steps_tree.column(key, width=width, minwidth=width, stretch=key == "name")
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.steps_tree.yview)
        self.steps_tree.configure(yscrollcommand=scrollbar.set)
        self.steps_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        buttons = ttk.Frame(parent)
        buttons.pack(fill=tk.X, pady=(7, 3))
        ttk.Button(buttons, text="添加到末尾", command=self.add_step).pack(side=tk.LEFT)
        ttk.Button(buttons, text="准备新步骤", command=self.prepare_append_step).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons, text="保存选中修改", command=self.update_step).pack(side=tk.LEFT)
        ttk.Button(buttons, text="删除", command=self.delete_step).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons, text="下移", command=lambda: self.move_step(1), width=6).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="上移", command=lambda: self.move_step(-1), width=6).pack(side=tk.RIGHT, padx=5)

        quick = ttk.Frame(parent)
        quick.pack(fill=tk.X, pady=(0, 7))
        ttk.Label(quick, text="快速添加").pack(side=tk.LEFT)
        ttk.Button(quick, text="输入文本", command=self.add_input_step).pack(side=tk.LEFT, padx=(8, 4))
        ttk.Button(quick, text="等待延迟", command=self.add_wait_step).pack(side=tk.LEFT)

        properties = ttk.LabelFrame(parent, text="步骤属性", padding=10)
        properties.pack(fill=tk.X)
        self._field(properties, 0, "名称", ttk.Entry(properties, textvariable=self.step_name_var))
        self._field(
            properties,
            1,
            "识别",
            ttk.Combobox(
                properties,
                textvariable=self.recognition_var,
                values=tuple(RECOGNITION_LABELS),
                state="readonly",
            ),
        )
        self._field(
            properties,
            2,
            "动作",
            ttk.Combobox(
                properties,
                textvariable=self.action_var,
                values=tuple(ACTION_LABELS),
                state="readonly",
            ),
        )
        self._field(properties, 3, "输入内容", ttk.Entry(properties, textvariable=self.input_var))
        self._field(properties, 4, "OCR 文字", ttk.Entry(properties, textvariable=self.expected_var))
        self._field(properties, 5, "匹配阈值", ttk.Entry(properties, textvariable=self.threshold_var))
        self._field(properties, 6, "按键码", ttk.Entry(properties, textvariable=self.key_var))
        self._field(properties, 7, "滑动时长 ms", ttk.Entry(properties, textvariable=self.duration_var))
        self._field(properties, 8, "执行前延迟 ms", ttk.Entry(properties, textvariable=self.pre_delay_var))
        self._field(properties, 9, "执行后延迟 ms", ttk.Entry(properties, textvariable=self.delay_var))
        self._field(properties, 10, "识别区域", ttk.Label(properties, textvariable=self.roi_var))
        self._field(properties, 11, "动作坐标", ttk.Label(properties, textvariable=self.target_var))
        properties.columnconfigure(1, weight=1)

        actions = ttk.Frame(parent)
        actions.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(actions, text="在设备上预览此动作", command=self.preview_step).pack(fill=tk.X)
    @staticmethod
    def _field(parent: ttk.LabelFrame, row: int, label: str, widget: tk.Widget) -> None:
        ttk.Label(parent, text=label, width=13).grid(row=row, column=0, sticky=tk.W, pady=3)
        widget.grid(row=row, column=1, sticky=tk.EW, pady=3)

    def _build_library_page(self, parent: ttk.Frame) -> None:
        category_row = ttk.Frame(parent)
        category_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(category_row, text="当前分类", width=10).pack(side=tk.LEFT)
        self.category_combo = ttk.Combobox(
            category_row,
            textvariable=self.category_var,
            values=("智能推荐", *SMART_CATEGORIES),
        )
        self.category_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(category_row, text="智能推荐", command=self.apply_suggested_category, width=9).pack(side=tk.LEFT, padx=(6, 0))

        search_row = ttk.Frame(parent)
        search_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(search_row, text="搜索作业", width=10).pack(side=tk.LEFT)
        search_entry = ttk.Entry(search_row, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        search_entry.bind("<KeyRelease>", lambda _event: self.refresh_jobs())

        ttk.Label(parent, text="共享作业库", style="Section.TLabel").pack(anchor=tk.W)
        self.jobs_tree = ttk.Treeview(parent, show="tree", height=9, selectmode="browse")
        self.jobs_tree.pack(fill=tk.BOTH, expand=True, pady=(5, 6))
        row = ttk.Frame(parent)
        row.pack(fill=tk.X)
        ttk.Button(row, text="载入", command=self.load_library_job).pack(side=tk.LEFT)
        ttk.Button(row, text="设为前置", command=self.add_prerequisite).pack(side=tk.LEFT, padx=6)
        ttk.Button(row, text="刷新", command=self.refresh_jobs).pack(side=tk.RIGHT)

        prerequisite_frame = ttk.LabelFrame(parent, text="前置用例（按顺序执行）", padding=8)
        prerequisite_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        self.prerequisite_list = tk.Listbox(prerequisite_frame, height=6, activestyle="dotbox")
        self.prerequisite_list.pack(fill=tk.BOTH, expand=True)
        prereq_buttons = ttk.Frame(prerequisite_frame)
        prereq_buttons.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(prereq_buttons, text="移除", command=self.remove_prerequisite).pack(side=tk.LEFT)
        ttk.Button(prereq_buttons, text="下移", command=lambda: self.move_prerequisite(1), width=6).pack(side=tk.RIGHT)
        ttk.Button(prereq_buttons, text="上移", command=lambda: self.move_prerequisite(-1), width=6).pack(side=tk.RIGHT, padx=5)
    def _bind_events(self) -> None:
        self.canvas.bind("<Configure>", lambda _event: self.render_canvas())
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.steps_tree.bind("<<TreeviewSelect>>", self.on_step_selected)
        self.jobs_tree.bind("<Double-Button-1>", lambda _event: self.load_library_job())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def run_background(self, operation, success_message: str, callback=None) -> None:
        self.status_var.set(success_message.replace("完成", "处理中…"))

        def worker() -> None:
            try:
                result = operation()
            except Exception as error:
                self.after(0, lambda: messagebox.showerror("操作失败", str(error), parent=self))
                self.after(0, lambda: self.status_var.set("操作失败"))
                return
            self.after(0, lambda: self.status_var.set(success_message))
            if callback:
                self.after(0, lambda: callback(result))

        threading.Thread(target=worker, daemon=True).start()

    def refresh_devices(self) -> None:
        def done(devices: list[str]) -> None:
            self.device_combo["values"] = devices
            if devices:
                current = self.device_var.get()
                self.device_var.set(current if current in devices else devices[0])
                self.adb.serial = self.device_var.get()
                self.status_var.set(f"已发现 {len(devices)} 台设备")
            else:
                self.device_var.set("")
                self.status_var.set("未发现已授权的 ADB 设备")

        self.run_background(self.adb.devices, "设备列表刷新完成", done)

    def capture_screen(self) -> None:
        serial = self.device_var.get()
        if not serial:
            messagebox.showwarning("没有设备", "请先连接并选择 ADB 设备", parent=self)
            return
        self.adb.serial = serial

        def done(image: np.ndarray) -> None:
            self.current_image = image
            height, width = image.shape[:2]
            self.document.device_size = [width, height]
            self.clear_selection()
            self.render_canvas()
            self.status_var.set(f"截图成功：{width} x {height}（Maa 坐标）")

        self.run_background(self.adb.screenshot, "截图完成", done)

    def render_canvas(self) -> None:
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 1)
        height = max(self.canvas.winfo_height(), 1)
        if self.current_image is None:
            self.canvas.create_text(
                width // 2,
                height // 2,
                text="连接 ADB 设备并点击“截图”",
                fill="#b8bec7",
                font=("Microsoft YaHei UI", 14),
            )
            return

        source_height, source_width = self.current_image.shape[:2]
        self.display_scale = min((width - 24) / source_width, (height - 24) / source_height)
        display_width = max(1, round(source_width * self.display_scale))
        display_height = max(1, round(source_height * self.display_scale))
        resized = cv2.resize(self.current_image, (display_width, display_height), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".png", resized)
        if not ok:
            return
        self.photo = tk.PhotoImage(data=base64.b64encode(encoded.tobytes()).decode("ascii"))
        origin_x = (width - display_width) // 2
        origin_y = (height - display_height) // 2
        self.display_origin = (origin_x, origin_y)
        self.canvas.create_image(origin_x, origin_y, image=self.photo, anchor=tk.NW, tags="screen")
        self._draw_markers()

    def _draw_markers(self) -> None:
        if self.selection_roi:
            x, y, width, height = self.selection_roi
            x1, y1 = self.image_to_canvas(x, y)
            x2, y2 = self.image_to_canvas(x + width, y + height)
            self.canvas.create_rectangle(x1, y1, x2, y2, outline="#35d07f", width=2, tags="marker")
        if self.selection_target:
            x, y = self.image_to_canvas(*self.selection_target)
            self.canvas.create_oval(x - 6, y - 6, x + 6, y + 6, outline="#ffcb45", width=3, tags="marker")
        if self.selection_target and self.selection_swipe_end:
            x1, y1 = self.image_to_canvas(*self.selection_target)
            x2, y2 = self.image_to_canvas(*self.selection_swipe_end)
            self.canvas.create_line(x1, y1, x2, y2, fill="#58a6ff", width=3, arrow=tk.LAST, tags="marker")

    def canvas_to_image(self, x: int, y: int) -> list[int] | None:
        if self.current_image is None:
            return None
        origin_x, origin_y = self.display_origin
        image_x = round((x - origin_x) / self.display_scale)
        image_y = round((y - origin_y) / self.display_scale)
        height, width = self.current_image.shape[:2]
        if not (0 <= image_x < width and 0 <= image_y < height):
            return None
        return [image_x, image_y]

    def image_to_canvas(self, x: int, y: int) -> tuple[int, int]:
        origin_x, origin_y = self.display_origin
        return round(origin_x + x * self.display_scale), round(origin_y + y * self.display_scale)

    def on_canvas_press(self, event) -> None:
        point = self.canvas_to_image(event.x, event.y)
        if point:
            self.drag_start = (point[0], point[1])

    def on_canvas_drag(self, event) -> None:
        if not self.drag_start:
            return
        point = self.canvas_to_image(event.x, event.y)
        if not point:
            return
        mode = self.mode_var.get()
        if mode == "template":
            x1, y1 = self.drag_start
            x2, y2 = point
            self.selection_roi = [min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)]
        elif mode == "swipe":
            self.selection_target = list(self.drag_start)
            self.selection_swipe_end = point
        self._update_selection_labels()
        self.render_canvas()

    def on_canvas_release(self, event) -> None:
        point = self.canvas_to_image(event.x, event.y)
        if not self.drag_start or not point:
            self.drag_start = None
            return
        mode = self.mode_var.get()
        if mode == "point":
            self.selection_target = point
            self.selection_swipe_end = None
        elif mode == "template" and self.selection_roi and (self.selection_roi[2] < 4 or self.selection_roi[3] < 4):
            self.selection_roi = None
        self.drag_start = None
        self._update_selection_labels()
        self.render_canvas()

    def clear_selection(self) -> None:
        self.selection_roi = None
        self.selection_target = None
        self.selection_swipe_end = None
        self._update_selection_labels()
        self.render_canvas()

    def _update_selection_labels(self) -> None:
        self.roi_var.set(str(self.selection_roi) if self.selection_roi else "未框选")
        if self.selection_target and self.selection_swipe_end:
            self.target_var.set(f"{self.selection_target} → {self.selection_swipe_end}")
        else:
            self.target_var.set(str(self.selection_target) if self.selection_target else "识别结果 / 未选择")

    def _step_from_form(self, existing_template: str = "") -> JobStep:
        try:
            threshold = float(self.threshold_var.get())
            key = int(self.key_var.get())
            duration = int(self.duration_var.get())
            pre_delay = int(self.pre_delay_var.get())
            post_delay = int(self.delay_var.get())
        except ValueError as error:
            raise ValueError("阈值、按键码、时长和延迟必须是数字") from error

        name = self.step_name_var.get().strip()
        recognition = RECOGNITION_LABELS[self.recognition_var.get()]
        template = existing_template
        if recognition == "TemplateMatch" and self.selection_roi and self.current_image is not None:
            template = self._save_template(name, self.selection_roi)

        return JobStep(
            name=name,
            recognition=recognition,
            action=ACTION_LABELS[self.action_var.get()],
            template=template,
            roi=self.selection_roi.copy() if self.selection_roi else None,
            expected=self.expected_var.get(),
            threshold=threshold,
            target=self.selection_target.copy() if self.selection_target else None,
            swipe_end=self.selection_swipe_end.copy() if self.selection_swipe_end else None,
            input_text=self.input_var.get(),
            key=key,
            duration=duration,
            pre_delay=pre_delay,
            post_delay=post_delay,
        )
    def _save_template(self, step_name: str, roi: list[int]) -> str:
        if self.current_image is None:
            raise ValueError("请先获取设备截图")
        x, y, width, height = roi
        if width < 4 or height < 4:
            raise ValueError("模板框选区域太小")
        crop = self.current_image[y : y + height, x : x + width]
        job_folder = safe_name(self.job_name_var.get(), "qq_job")
        filename = f"{safe_name(step_name, 'step')}.png"
        output = IMAGE_DIR / job_folder / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        ok, encoded = cv2.imencode(".png", crop)
        if not ok:
            raise ValueError("模板图片编码失败")
        encoded.tofile(output)
        return f"jobs/{job_folder}/{filename}"

    def add_step(self) -> None:
        try:
            step = self._step_from_form()
            errors = step.validate()
            if errors:
                raise ValueError("\n".join(errors))
            if any(item.name == step.name for item in self.document.steps):
                raise ValueError("步骤名称不能重复")
        except Exception as error:
            messagebox.showerror("无法新增步骤", str(error), parent=self)
            return
        self.document.steps.append(step)
        self.dirty = True
        self.refresh_steps(select=len(self.document.steps) - 1)
        self._prepare_next_step()
        self.status_var.set(f"已新增：{step.name}")

    def add_input_step(self) -> None:
        value = simpledialog.askstring("添加输入步骤", "请输入要写入 QQ App 的文本：", parent=self)
        if value is None:
            return
        if not value:
            messagebox.showwarning("输入为空", "输入内容不能为空", parent=self)
            return
        self.step_name_var.set(f"输入文本 {len(self.document.steps) + 1}")
        self.recognition_var.set(RECOGNITION_NAMES["DirectHit"])
        self.action_var.set(ACTION_NAMES["InputText"])
        self.input_var.set(value)
        self.pre_delay_var.set("0")
        self.delay_var.set("300")
        self.clear_selection()
        self.add_step()

    def add_wait_step(self) -> None:
        milliseconds = simpledialog.askinteger(
            "添加等待步骤",
            "等待时间（毫秒）：",
            parent=self,
            initialvalue=1000,
            minvalue=0,
            maxvalue=600000,
        )
        if milliseconds is None:
            return
        self.step_name_var.set(f"等待 {milliseconds}ms")
        self.recognition_var.set(RECOGNITION_NAMES["DirectHit"])
        self.action_var.set(ACTION_NAMES["DoNothing"])
        self.pre_delay_var.set(str(milliseconds))
        self.delay_var.set("0")
        self.clear_selection()
        self.add_step()
    def update_step(self) -> None:
        index = self.selected_step_index()
        if index is None:
            messagebox.showinfo("选择步骤", "请先在列表中选择要修改的步骤", parent=self)
            return
        existing = self.document.steps[index]
        try:
            step = self._step_from_form(existing.template)
            errors = step.validate()
            if errors:
                raise ValueError("\n".join(errors))
            if any(item.name == step.name for item_index, item in enumerate(self.document.steps) if item_index != index):
                raise ValueError("步骤名称不能重复")
        except Exception as error:
            messagebox.showerror("无法应用修改", str(error), parent=self)
            return
        self.document.steps[index] = step
        self.dirty = True
        self.refresh_steps(select=index)
        self.status_var.set(f"已更新：{step.name}")

    def delete_step(self) -> None:
        index = self.selected_step_index()
        if index is None:
            return
        step = self.document.steps[index]
        if not messagebox.askyesno("删除步骤", f"确定删除“{step.name}”吗？", parent=self):
            return
        del self.document.steps[index]
        self.dirty = True
        self.refresh_steps(select=min(index, len(self.document.steps) - 1))

    def move_step(self, offset: int) -> None:
        index = self.selected_step_index()
        if index is None:
            return
        target = index + offset
        if not 0 <= target < len(self.document.steps):
            return
        self.document.steps[index], self.document.steps[target] = self.document.steps[target], self.document.steps[index]
        self.dirty = True
        self.refresh_steps(select=target)

    def selected_step_index(self) -> int | None:
        selected = self.steps_tree.selection()
        return int(selected[0]) if selected else None

    def refresh_steps(self, select: int | None = None) -> None:
        self.steps_tree.delete(*self.steps_tree.get_children())
        for index, step in enumerate(self.document.steps):
            self.steps_tree.insert("", tk.END, iid=str(index), values=(index + 1, step.name, RECOGNITION_NAMES[step.recognition], ACTION_NAMES[step.action]))
        if select is not None and 0 <= select < len(self.document.steps):
            self.steps_tree.selection_set(str(select))
            self.steps_tree.focus(str(select))

    def on_step_selected(self, _event=None) -> None:
        index = self.selected_step_index()
        if index is None:
            return
        step = self.document.steps[index]
        self.step_name_var.set(step.name)
        self.recognition_var.set(RECOGNITION_NAMES[step.recognition])
        self.action_var.set(ACTION_NAMES[step.action])
        self.expected_var.set(step.expected)
        self.threshold_var.set(f"{step.threshold:.2f}")
        self.input_var.set(step.input_text)
        self.key_var.set(str(step.key))
        self.duration_var.set(str(step.duration))
        self.pre_delay_var.set(str(step.pre_delay))
        self.delay_var.set(str(step.post_delay))
        self.selection_roi = step.roi.copy() if step.roi else None
        self.selection_target = step.target.copy() if step.target else None
        self.selection_swipe_end = step.swipe_end.copy() if step.swipe_end else None
        self._update_selection_labels()
        self.render_canvas()

    def prepare_append_step(self) -> None:
        self.steps_tree.selection_remove(self.steps_tree.selection())
        self._prepare_next_step()
        self.status_var.set("已准备追加新步骤，填写属性后点击“添加到末尾”")
    def _prepare_next_step(self) -> None:
        self.step_name_var.set(f"步骤 {len(self.document.steps) + 1}")
        self.recognition_var.set(RECOGNITION_NAMES["TemplateMatch"])
        self.action_var.set(ACTION_NAMES["Click"])
        self.expected_var.set("")
        self.input_var.set("")
        self.pre_delay_var.set("0")
        self.delay_var.set("500")
        self.clear_selection()
    def new_job(self) -> None:
        if not self.confirm_discard():
            return
        self.document = JobDocument()
        self.current_path = None
        self.job_name_var.set(self.document.name)
        self.category_var.set("智能推荐")
        self.dirty = False
        self.refresh_steps()
        self.refresh_prerequisites()
        self._prepare_next_step()
        self.status_var.set("已新建作业，首次保存会自动生成路径")
    def apply_suggested_category(self) -> None:
        category = suggest_category(self.job_name_var.get().strip(), self.document.steps)
        self.category_var.set(category)
        self.status_var.set(f"已推荐分类：{category}")

    def sync_document_metadata(self) -> None:
        self.document.name = self.job_name_var.get().strip()
        category = self.category_var.get().strip()
        if not category or category in {"智能推荐", "默认"}:
            category = suggest_category(self.document.name, self.document.steps)
            self.category_var.set(category)
        self.document.category = category

    def default_job_path(self) -> Path:
        folder = JOBS_DIR / safe_name(self.document.category, "通用流程")
        folder.mkdir(parents=True, exist_ok=True)
        candidate = folder / f"{safe_name(self.document.name)}.maa_job.json"
        suffix = 2
        while candidate.exists() and (self.current_path is None or candidate.resolve() != self.current_path.resolve()):
            candidate = folder / f"{safe_name(self.document.name)}_{suffix}.maa_job.json"
            suffix += 1
        return candidate

    def save_job(self, save_as: bool = False) -> bool:
        self.sync_document_metadata()
        errors = self.document.validate()
        if errors:
            messagebox.showerror("作业校验失败", "\n".join(errors), parent=self)
            return False
        path = self.current_path
        if save_as:
            initial = self.default_job_path()
            path_text = filedialog.asksaveasfilename(
                parent=self,
                title="作业另存为",
                initialdir=initial.parent,
                initialfile=initial.name,
                defaultextension=".json",
                filetypes=(("Maa 作业", "*.maa_job.json"), ("JSON", "*.json")),
            )
            if not path_text:
                return False
            path = Path(path_text)
        elif path is None:
            path = self.default_job_path()
        try:
            self.document.save(path)
        except Exception as error:
            messagebox.showerror("保存失败", str(error), parent=self)
            return False
        self.current_path = path
        self.dirty = False
        self.refresh_jobs()
        self.status_var.set(f"已保存：{path.relative_to(JOBS_DIR) if path.is_relative_to(JOBS_DIR) else path}")
        return True
    def open_job(self, path: Path | None = None) -> None:
        if not self.confirm_discard():
            return
        if path is None:
            path_text = filedialog.askopenfilename(
                parent=self,
                title="打开作业",
                initialdir=JOBS_DIR,
                filetypes=(("Maa 作业", "*.maa_job.json"), ("JSON", "*.json")),
            )
            if not path_text:
                return
            path = Path(path_text)
        try:
            self.document = JobDocument.load(path)
        except Exception as error:
            messagebox.showerror("载入失败", str(error), parent=self)
            return
        self.current_path = path
        self.job_name_var.set(self.document.name)
        self.category_var.set(self.document.category)
        self.dirty = False
        self.refresh_steps()
        self.refresh_prerequisites()
        self._prepare_next_step()
        self.status_var.set(f"已载入，可继续追加：{self.document.category} / {path.name}")
    def refresh_jobs(self) -> None:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        self.jobs_tree.delete(*self.jobs_tree.get_children())
        self.job_paths.clear()
        grouped: dict[str, list[tuple[str, Path]]] = {}
        query = self.search_var.get().strip().casefold()
        for path in sorted(JOBS_DIR.rglob("*.maa_job.json")):
            try:
                document = JobDocument.load(path)
                category = document.category or suggest_category(document.name, document.steps)
                display_name = document.name or path.stem
            except Exception:
                category = "文件异常"
                display_name = path.stem
            searchable = f"{category} {display_name} {path.name}".casefold()
            if query and query not in searchable:
                continue
            grouped.setdefault(category, []).append((display_name, path))

        preferred = {name: index for index, name in enumerate(SMART_CATEGORIES)}
        categories = sorted(grouped, key=lambda name: (preferred.get(name, 999), name))
        choices = ["智能推荐", *SMART_CATEGORIES, *(name for name in categories if name not in SMART_CATEGORIES)]
        self.category_combo["values"] = tuple(dict.fromkeys(choices))
        for category_index, category in enumerate(categories):
            items = sorted(grouped[category], key=lambda item: item[0])
            category_id = f"category_{category_index}"
            self.jobs_tree.insert("", tk.END, iid=category_id, text=f"{category}  ({len(items)})", open=True)
            for job_index, (display_name, path) in enumerate(items):
                item_id = f"job_{category_index}_{job_index}"
                self.jobs_tree.insert(category_id, tk.END, iid=item_id, text=display_name)
                self.job_paths[item_id] = path
        if not categories:
            self.jobs_tree.insert("", tk.END, text="没有匹配的作业")
    def selected_library_path(self) -> Path | None:
        selected = self.jobs_tree.selection()
        return self.job_paths.get(selected[0]) if selected else None

    def load_library_job(self) -> None:
        path = self.selected_library_path()
        if path:
            self.open_job(path)

    def add_prerequisite(self) -> None:
        path = self.selected_library_path()
        if path is None:
            messagebox.showinfo("选择用例", "请在分类作业库中选择一个用例", parent=self)
            return
        if self.current_path and path.resolve() == self.current_path.resolve():
            messagebox.showerror("不能添加", "当前作业不能作为自己的前置用例", parent=self)
            return
        reference = path.relative_to(JOBS_DIR).as_posix()
        if reference in self.document.prerequisites:
            messagebox.showinfo("已经添加", "该用例已在前置列表中", parent=self)
            return
        self.document.prerequisites.append(reference)
        self.dirty = True
        self.refresh_prerequisites(select=len(self.document.prerequisites) - 1)

    def remove_prerequisite(self) -> None:
        selected = self.prerequisite_list.curselection()
        if not selected:
            return
        del self.document.prerequisites[selected[0]]
        self.dirty = True
        self.refresh_prerequisites()

    def move_prerequisite(self, offset: int) -> None:
        selected = self.prerequisite_list.curselection()
        if not selected:
            return
        index = selected[0]
        target = index + offset
        if not 0 <= target < len(self.document.prerequisites):
            return
        items = self.document.prerequisites
        items[index], items[target] = items[target], items[index]
        self.dirty = True
        self.refresh_prerequisites(select=target)

    def refresh_prerequisites(self, select: int | None = None) -> None:
        self.prerequisite_list.delete(0, tk.END)
        for index, reference in enumerate(self.document.prerequisites, start=1):
            self.prerequisite_list.insert(tk.END, f"{index}. {reference}")
        if select is not None and 0 <= select < len(self.document.prerequisites):
            self.prerequisite_list.selection_set(select)
    def export_pipeline(self) -> None:
        self.document.name = self.job_name_var.get().strip()
        self.document.category = self.category_var.get().strip() or "默认"
        errors = self.document.validate()
        if errors:
            messagebox.showerror("不能导出", "\n".join(errors), parent=self)
            return
        PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
        path_text = filedialog.asksaveasfilename(
            parent=self,
            title="导出 Maa Pipeline",
            initialdir=PIPELINE_DIR,
            initialfile=f"{safe_name(self.document.name)}.json",
            defaultextension=".json",
            filetypes=(("Maa Pipeline", "*.json"),),
        )
        if not path_text:
            return
        try:
            self.document.export_pipeline(Path(path_text), JOBS_DIR)
        except Exception as error:
            messagebox.showerror("导出失败", str(error), parent=self)
            return
        entry = safe_name(self.document.name, "QQJob")
        self.status_var.set(f"Pipeline 已导出，入口节点：{entry}")
        messagebox.showinfo("导出成功", f"入口节点：{entry}\n文件：{path_text}", parent=self)

    def preview_step(self) -> None:
        index = self.selected_step_index()
        if index is None:
            messagebox.showinfo("选择步骤", "请先选择步骤", parent=self)
            return
        self.adb.serial = self.device_var.get()
        step = self.document.steps[index]

        def operation() -> None:
            if step.pre_delay:
                time.sleep(step.pre_delay / 1000)
            if step.action == "Click":
                target = step.target
                if step.recognition == "TemplateMatch":
                    target = self._find_template_center(step)
                if not target:
                    raise RuntimeError("该步骤没有可用于预览的固定坐标")
                self.adb.tap(target)
            elif step.action == "Swipe":
                self.adb.swipe(step.target or [], step.swipe_end or [], step.duration)
            elif step.action == "InputText":
                self.adb.input_text(step.input_text)
            elif step.action == "ClickKey":
                self.adb.keyevent(step.key)
            elif step.action == "DoNothing":
                pass
            if step.post_delay:
                time.sleep(step.post_delay / 1000)

        self.run_background(operation, f"已在设备上执行：{step.name}")

    def _find_template_center(self, step: JobStep) -> list[int]:
        screen = self.adb.screenshot()
        template_path = ASSETS_DIR / "resource" / "image" / step.template
        template = cv2.imdecode(np.fromfile(template_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if template is None:
            raise RuntimeError(f"无法读取模板：{template_path}")
        search = screen
        offset_x = 0
        offset_y = 0
        if step.roi:
            offset_x, offset_y, width, height = step.roi
            search = screen[offset_y : offset_y + height, offset_x : offset_x + width]
        if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
            raise RuntimeError("模板尺寸大于识别区域")
        result = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if score < step.threshold:
            raise RuntimeError(f"模板未命中：最高相似度 {score:.3f}，阈值 {step.threshold:.3f}")
        x = offset_x + location[0] + template.shape[1] // 2
        y = offset_y + location[1] + template.shape[0] // 2
        return [x, y]

    def open_runner(self) -> None:
        if self.dirty and self.document.steps and not self.save_job():
            return
        from job_runner_app import JobRunnerWindow

        self.withdraw()
        JobRunnerWindow(self)
    def confirm_discard(self) -> bool:
        return not self.dirty or messagebox.askyesno("未保存修改", "当前修改尚未保存，确定继续吗？", parent=self)

    def on_close(self) -> None:
        if self.confirm_discard():
            self.destroy()


def main() -> None:
    editor = JobEditor()
    editor.mainloop()


if __name__ == "__main__":
    main()
