"""MAA-style job execution window sharing the editor job library."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from job_model import SMART_CATEGORIES, JobDocument, suggest_category
from job_runner import MaaJobRunner


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
ASSETS_DIR = APP_DIR / "assets"
JOBS_DIR = APP_DIR / "jobs"


class JobRunnerWindow(tk.Toplevel):
    def __init__(self, parent: tk.Tk) -> None:
        super().__init__(parent)
        self.parent = parent
        self.runner = MaaJobRunner(APP_DIR, ASSETS_DIR, JOBS_DIR)
        self.job_paths: dict[str, Path] = {}
        self.queue: list[Path] = []
        self.stop_requested = False
        self.worker: threading.Thread | None = None

        self.device_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.StringVar(value="请选择作业加入执行队列")

        self.title("QQ App 作业执行")
        self.geometry("1220x780")
        self.minsize(980, 680)
        self.protocol("WM_DELETE_WINDOW", self.back_to_editor)
        self._build_ui()
        self.refresh_library()
        self.refresh_devices()

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(14, 10))
        header.pack(fill=tk.X)
        ttk.Button(header, text="返回用例录制", command=self.back_to_editor, width=13).pack(side=tk.LEFT)
        ttk.Label(header, text="QQ App 作业执行", font=("Microsoft YaHei UI", 14, "bold")).pack(side=tk.LEFT, padx=14)
        ttk.Label(header, textvariable=self.status_var, foreground="#26734d").pack(side=tk.RIGHT)

        controller_bar = ttk.Frame(self, padding=(14, 0, 14, 10))
        controller_bar.pack(fill=tk.X)
        ttk.Label(controller_bar, text="ADB 设备").pack(side=tk.LEFT)
        self.device_combo = ttk.Combobox(controller_bar, textvariable=self.device_var, width=28, state="readonly")
        self.device_combo.pack(side=tk.LEFT, padx=(8, 5))
        ttk.Button(controller_bar, text="刷新设备", command=self.refresh_devices, width=10).pack(side=tk.LEFT)
        ttk.Label(controller_bar, textvariable=self.progress_var).pack(side=tk.RIGHT)

        body = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 10))
        library = ttk.Frame(body, width=330, padding=(0, 0, 12, 0))
        workspace = ttk.Frame(body)
        body.add(library, weight=1)
        body.add(workspace, weight=3)

        ttk.Label(library, text="作业库", font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W)
        search_row = ttk.Frame(library)
        search_row.pack(fill=tk.X, pady=(8, 8))
        ttk.Entry(search_row, textvariable=self.search_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(search_row, text="搜索", command=self.refresh_library, width=7).pack(side=tk.LEFT, padx=(5, 0))
        self.search_var.trace_add("write", lambda *_args: self.refresh_library())

        self.library_tree = ttk.Treeview(library, show="tree", selectmode="browse")
        self.library_tree.pack(fill=tk.BOTH, expand=True)
        self.library_tree.bind("<Double-Button-1>", lambda _event: self.add_selected_job())
        ttk.Button(library, text="加入执行队列", command=self.add_selected_job).pack(fill=tk.X, pady=(8, 0))

        queue_header = ttk.Frame(workspace)
        queue_header.pack(fill=tk.X)
        ttk.Label(queue_header, text="执行队列", font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT)
        ttk.Button(queue_header, text="清空", command=self.clear_queue, width=7).pack(side=tk.RIGHT)
        ttk.Button(queue_header, text="下移", command=lambda: self.move_queue(1), width=7).pack(side=tk.RIGHT, padx=5)
        ttk.Button(queue_header, text="上移", command=lambda: self.move_queue(-1), width=7).pack(side=tk.RIGHT)
        ttk.Button(queue_header, text="移除", command=self.remove_queue_item, width=7).pack(side=tk.RIGHT, padx=5)

        columns = ("index", "name", "category", "prerequisites")
        self.queue_tree = ttk.Treeview(workspace, columns=columns, show="headings", height=10, selectmode="browse")
        for key, title, width in (
            ("index", "#", 42),
            ("name", "作业", 220),
            ("category", "分类", 130),
            ("prerequisites", "前置用例", 260),
        ):
            self.queue_tree.heading(key, text=title)
            self.queue_tree.column(key, width=width, stretch=key in {"name", "prerequisites"})
        self.queue_tree.pack(fill=tk.X, pady=(8, 12))

        log_frame = ttk.LabelFrame(workspace, text="执行日志", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(
            log_frame,
            state=tk.DISABLED,
            wrap=tk.WORD,
            background="#f7f8fa",
            foreground="#252a31",
            relief=tk.FLAT,
            padx=10,
            pady=10,
            font=("Microsoft YaHei UI", 9),
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

        footer = ttk.Frame(self, padding=(14, 0, 14, 14))
        footer.pack(fill=tk.X)
        self.stop_button = ttk.Button(footer, text="停止", command=self.stop_execution, width=12, state=tk.DISABLED)
        self.stop_button.pack(side=tk.RIGHT)
        self.start_button = ttk.Button(footer, text="开始执行", command=self.start_execution, width=16)
        self.start_button.pack(side=tk.RIGHT, padx=(0, 8))

    def adb_executable(self) -> str:
        bundled = APP_DIR / "platform-tools" / "adb.exe"
        return str(bundled) if bundled.exists() else "adb"

    def refresh_devices(self) -> None:
        try:
            result = subprocess.run(
                [self.adb_executable(), "devices"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            devices = [line.split()[0] for line in result.stdout.splitlines()[1:] if line.strip().endswith("device")]
        except Exception as error:
            messagebox.showerror("设备刷新失败", str(error), parent=self)
            return
        self.device_combo["values"] = devices
        if devices:
            self.device_var.set(self.device_var.get() if self.device_var.get() in devices else devices[0])
            self.status_var.set(f"已连接 {len(devices)} 台设备")
        else:
            self.device_var.set("")
            self.status_var.set("未发现 ADB 设备")

    def refresh_library(self) -> None:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        self.library_tree.delete(*self.library_tree.get_children())
        self.job_paths.clear()
        query = self.search_var.get().strip().casefold()
        grouped: dict[str, list[tuple[str, Path]]] = {}
        for path in sorted(JOBS_DIR.rglob("*.maa_job.json")):
            try:
                document = JobDocument.load(path)
            except Exception:
                continue
            category = document.category or suggest_category(document.name, document.steps)
            if query and query not in f"{document.name} {category}".casefold():
                continue
            grouped.setdefault(category, []).append((document.name, path))

        preferred = {name: index for index, name in enumerate(SMART_CATEGORIES)}
        categories = sorted(grouped, key=lambda value: (preferred.get(value, 999), value))
        for category_index, category in enumerate(categories):
            items = sorted(grouped[category], key=lambda item: item[0])
            parent_id = f"category_{category_index}"
            self.library_tree.insert("", tk.END, iid=parent_id, text=f"{category}  ({len(items)})", open=True)
            for job_index, (name, path) in enumerate(items):
                item_id = f"job_{category_index}_{job_index}"
                self.library_tree.insert(parent_id, tk.END, iid=item_id, text=name)
                self.job_paths[item_id] = path
        if not categories:
            self.library_tree.insert("", tk.END, text="没有可执行作业")

    def selected_library_path(self) -> Path | None:
        selected = self.library_tree.selection()
        return self.job_paths.get(selected[0]) if selected else None

    def add_selected_job(self) -> None:
        path = self.selected_library_path()
        if path is None:
            return
        self.queue.append(path)
        self.refresh_queue(select=len(self.queue) - 1)

    def refresh_queue(self, select: int | None = None) -> None:
        self.queue_tree.delete(*self.queue_tree.get_children())
        valid_queue: list[Path] = []
        for path in self.queue:
            try:
                document = JobDocument.load(path)
            except Exception as error:
                self.append_log(f"跳过损坏作业 {path.name}: {error}")
                continue
            valid_queue.append(path)
            prerequisites = " → ".join(document.prerequisites) if document.prerequisites else "无"
            index = len(valid_queue) - 1
            self.queue_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(index + 1, document.name, document.category, prerequisites),
            )
        self.queue = valid_queue
        if select is not None and 0 <= select < len(self.queue):
            self.queue_tree.selection_set(str(select))

    def selected_queue_index(self) -> int | None:
        selected = self.queue_tree.selection()
        return int(selected[0]) if selected else None

    def remove_queue_item(self) -> None:
        index = self.selected_queue_index()
        if index is None:
            return
        del self.queue[index]
        self.refresh_queue(select=min(index, len(self.queue) - 1))

    def clear_queue(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.queue.clear()
        self.refresh_queue()

    def move_queue(self, offset: int) -> None:
        index = self.selected_queue_index()
        if index is None:
            return
        target = index + offset
        if not 0 <= target < len(self.queue):
            return
        self.queue[index], self.queue[target] = self.queue[target], self.queue[index]
        self.refresh_queue(select=target)

    def append_log(self, message: str) -> None:
        def update() -> None:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)
        if threading.current_thread() is threading.main_thread():
            update()
        else:
            self.after(0, update)

    def start_execution(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.queue:
            messagebox.showinfo("执行队列为空", "请先从左侧加入至少一个作业", parent=self)
            return
        if not self.device_var.get():
            messagebox.showwarning("没有设备", "请选择 ADB 设备", parent=self)
            return
        self.stop_requested = False
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.status_var.set("执行中")
        self.worker = threading.Thread(target=self._run_queue, daemon=True)
        self.worker.start()

    def _run_queue(self) -> None:
        total = len(self.queue)
        completed = 0
        try:
            for index, path in enumerate(list(self.queue), start=1):
                if self.stop_requested:
                    break
                document = JobDocument.load(path)
                self.after(0, lambda i=index, n=document.name: self.progress_var.set(f"{i}/{total}  {n}"))
                self.append_log(f"\n[{index}/{total}] 开始：{document.name}")
                succeeded = self.runner.run(document, self.device_var.get(), self.append_log)
                if not succeeded:
                    self.append_log(f"失败：{document.name}")
                    break
                completed += 1
                self.append_log(f"完成：{document.name}")
        except Exception as error:
            self.append_log(f"执行异常：{error}")
        finally:
            stopped = self.stop_requested
            self.after(0, lambda: self._execution_finished(completed, total, stopped))

    def _execution_finished(self, completed: int, total: int, stopped: bool) -> None:
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.status_var.set("已停止" if stopped else ("执行完成" if completed == total else "执行失败"))
        self.progress_var.set(f"完成 {completed}/{total}")

    def stop_execution(self) -> None:
        if not self.worker or not self.worker.is_alive():
            return
        self.stop_requested = True
        threading.Thread(target=lambda: self.runner.stop(self.append_log), daemon=True).start()

    def back_to_editor(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("作业正在执行", "停止执行并返回录制界面吗？", parent=self):
                return
            self.stop_execution()
        self.destroy()
        self.parent.deiconify()
        self.parent.lift()
