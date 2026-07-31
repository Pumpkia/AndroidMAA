"""Embedded MaaFramework job runner used by the visual job editor."""

from __future__ import annotations

from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from job_model import SMART_CATEGORIES, JobDocument, suggest_category
from job_runner import MaaJobRunner


APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
ASSETS_DIR = APP_DIR / "assets"
JOBS_DIR = APP_DIR / "jobs"


class JobRunnerPanel(ttk.Frame):
    """Compact playback workspace embedded in the editor's right-hand pane."""

    def __init__(
        self,
        parent: tk.Misc,
        device_var: tk.StringVar,
        on_record_requested: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent, style="Panel.TFrame", padding=(16, 14))
        self.device_var = device_var
        self.on_record_requested = on_record_requested
        self.runner = MaaJobRunner(APP_DIR, ASSETS_DIR, JOBS_DIR)
        self.job_paths: dict[str, Path] = {}
        self.queue: list[Path] = []
        self.stop_requested = False
        self.worker: threading.Thread | None = None
        self._closing = False

        self.search_var = tk.StringVar(master=self)
        self.status_var = tk.StringVar(master=self, value="就绪")
        self.progress_var = tk.StringVar(master=self, value="从作业库选择任务并加入执行队列")
        self.device_summary_var = tk.StringVar(master=self)
        self.library_count_var = tk.StringVar(master=self, value="0 个作业")
        self.queue_count_var = tk.StringVar(master=self, value="0 项")

        self._build_ui()
        self._search_trace = self.search_var.trace_add("write", self._on_search_changed)
        self._device_trace = self.device_var.trace_add("write", self._on_device_changed)
        self._sync_device_summary()
        self.activate()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=3, minsize=140)
        self.rowconfigure(4, weight=3, minsize=140)
        self.rowconfigure(6, weight=2, minsize=110)

        self._build_header()
        ttk.Separator(self, orient=tk.HORIZONTAL).grid(row=1, column=0, sticky="ew")
        self._build_library()
        ttk.Separator(self, orient=tk.HORIZONTAL).grid(row=3, column=0, sticky="ew")
        self._build_queue()
        ttk.Separator(self, orient=tk.HORIZONTAL).grid(row=5, column=0, sticky="ew")
        self._build_log()
        self._build_footer()

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)

        title_group = ttk.Frame(header, style="Panel.TFrame")
        title_group.grid(row=0, column=0, sticky="w")
        ttk.Label(title_group, text="步骤回放", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            title_group,
            textvariable=self.device_summary_var,
            style="Muted.TLabel",
            wraplength=340,
        ).pack(anchor=tk.W, pady=(3, 0))

        status_group = ttk.Frame(header, style="Panel.TFrame")
        status_group.grid(row=0, column=1, sticky="ne", padx=(12, 0))
        ttk.Label(status_group, text="状态", style="Muted.TLabel").pack(anchor=tk.E)
        ttk.Label(status_group, textvariable=self.status_var, style="Section.TLabel").pack(anchor=tk.E, pady=(3, 0))

    def _build_library(self) -> None:
        library = ttk.Frame(self, style="Panel.TFrame", padding=(0, 10))
        library.grid(row=2, column=0, sticky="nsew")
        library.columnconfigure(0, weight=1)
        library.rowconfigure(2, weight=1)

        section_header = ttk.Frame(library, style="Panel.TFrame")
        section_header.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        section_header.columnconfigure(0, weight=1)
        ttk.Label(section_header, text="作业库", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(section_header, textvariable=self.library_count_var, style="Muted.TLabel").grid(
            row=0, column=1, sticky="e"
        )

        search_row = ttk.Frame(library, style="Panel.TFrame")
        search_row.grid(row=1, column=0, sticky="ew", pady=(0, 7))
        search_row.columnconfigure(1, weight=1)
        ttk.Label(search_row, text="搜索", style="Muted.TLabel").grid(row=0, column=0, padx=(0, 7))
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=1, sticky="ew")
        self.search_entry.bind("<Return>", lambda _event: self.refresh_library())
        ttk.Button(search_row, text="刷新", command=self.refresh_library, width=6).grid(row=0, column=2, padx=(7, 0))

        tree_frame = ttk.Frame(library, style="Panel.TFrame")
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.library_tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse", height=5)
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.library_tree.yview)
        self.library_tree.configure(yscrollcommand=scrollbar.set)
        self.library_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.library_tree.bind("<<TreeviewSelect>>", lambda _event: self._update_action_states())
        self.library_tree.bind("<Double-Button-1>", lambda _event: self.add_selected_job())
        self.library_tree.bind("<Return>", lambda _event: self.add_selected_job())

        self.add_button = ttk.Button(
            library,
            text="加入执行队列",
            command=self.add_selected_job,
            style="Primary.TButton",
        )
        self.add_button.grid(row=3, column=0, sticky="ew", pady=(7, 0))

    def _build_queue(self) -> None:
        queue_section = ttk.Frame(self, style="Panel.TFrame", padding=(0, 10))
        queue_section.grid(row=4, column=0, sticky="nsew")
        queue_section.columnconfigure(0, weight=1)
        queue_section.rowconfigure(1, weight=1)

        header = ttk.Frame(queue_section, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="执行队列", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.queue_count_var, style="Muted.TLabel").grid(
            row=0, column=1, padx=(6, 8)
        )
        self.remove_button = ttk.Button(header, text="移除", command=self.remove_queue_item, width=5)
        self.remove_button.grid(row=0, column=2, padx=2)
        self.move_up_button = ttk.Button(header, text="上移", command=lambda: self.move_queue(-1), width=5)
        self.move_up_button.grid(row=0, column=3, padx=2)
        self.move_down_button = ttk.Button(header, text="下移", command=lambda: self.move_queue(1), width=5)
        self.move_down_button.grid(row=0, column=4, padx=2)
        self.clear_button = ttk.Button(header, text="清空", command=self.clear_queue, width=5)
        self.clear_button.grid(row=0, column=5, padx=(2, 0))

        tree_frame = ttk.Frame(queue_section, style="Panel.TFrame")
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        columns = ("index", "name", "category", "prerequisites")
        self.queue_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            height=5,
            selectmode="browse",
        )
        for key, title, width, stretch in (
            ("index", "#", 34, False),
            ("name", "作业", 140, True),
            ("category", "分类", 78, False),
            ("prerequisites", "前置用例", 150, True),
        ):
            self.queue_tree.heading(key, text=title)
            self.queue_tree.column(key, width=width, minwidth=width if not stretch else 75, stretch=stretch)
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=scrollbar.set)
        self.queue_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.queue_tree.bind("<<TreeviewSelect>>", lambda _event: self._update_action_states())
        self.queue_tree.bind("<Delete>", lambda _event: self.remove_queue_item())
        self.queue_tree.bind("<Control-Up>", lambda _event: self.move_queue(-1))
        self.queue_tree.bind("<Control-Down>", lambda _event: self.move_queue(1))

    def _build_log(self) -> None:
        log_section = ttk.Frame(self, style="Panel.TFrame", padding=(0, 10))
        log_section.grid(row=6, column=0, sticky="nsew")
        log_section.columnconfigure(0, weight=1)
        log_section.rowconfigure(1, weight=1)

        header = ttk.Frame(log_section, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="执行日志", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="清空日志", command=self.clear_log, width=8).grid(row=0, column=1, sticky="e")

        log_frame = ttk.Frame(log_section, style="Panel.TFrame")
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        style = ttk.Style(self)
        background = style.lookup("Panel.TFrame", "background") or style.lookup("TFrame", "background") or "#ffffff"
        foreground = style.lookup("TLabel", "foreground") or "#20242a"
        self.log_text = tk.Text(
            log_frame,
            state=tk.DISABLED,
            wrap=tk.WORD,
            background=background,
            foreground=foreground,
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=style.lookup("TSeparator", "background") or "#d8dde5",
            padx=10,
            pady=8,
            font=("Microsoft YaHei UI", 9),
            width=40,
            height=4,
        )
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def _build_footer(self) -> None:
        footer = ttk.Frame(self, style="Panel.TFrame")
        footer.grid(row=7, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(
            footer,
            textvariable=self.progress_var,
            style="Muted.TLabel",
            wraplength=255,
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.stop_button = ttk.Button(
            footer,
            text="停止",
            command=self.stop_execution,
            style="Danger.TButton",
            width=8,
            state=tk.DISABLED,
        )
        self.stop_button.grid(row=0, column=1, padx=(0, 7))
        self.start_button = ttk.Button(
            footer,
            text="开始执行",
            command=self.start_execution,
            style="Primary.TButton",
            width=11,
        )
        self.start_button.grid(row=0, column=2)

    def activate(self) -> None:
        """Refresh disk-backed state whenever the playback view becomes active."""
        if self._closing:
            return
        self.refresh_library()
        self.refresh_queue()
        self._sync_device_summary()
        self._update_action_states()
        try:
            self.after_idle(self.search_entry.focus_set)
        except tk.TclError:
            pass

    def _on_search_changed(self, *_args: object) -> None:
        self.refresh_library()

    def _on_device_changed(self, *_args: object) -> None:
        self._sync_device_summary()

    def _sync_device_summary(self) -> None:
        try:
            device = self.device_var.get().strip()
        except tk.TclError:
            device = ""
        self.device_summary_var.set(f"设备 · {device}" if device else "设备 · 尚未连接")

    def refresh_library(self) -> None:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        self.library_tree.delete(*self.library_tree.get_children())
        self.job_paths.clear()
        query = self.search_var.get().strip().casefold()
        grouped: dict[str, list[tuple[str, Path]]] = {}
        job_count = 0
        for path in sorted(JOBS_DIR.rglob("*.maa_job.json")):
            try:
                document = JobDocument.load(path)
            except Exception:
                continue
            category = document.category or suggest_category(document.name, document.steps)
            if query and query not in f"{document.name} {category}".casefold():
                continue
            grouped.setdefault(category, []).append((document.name, path))
            job_count += 1

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
            empty_text = "没有匹配的作业" if query else "作业库为空"
            self.library_tree.insert("", tk.END, iid="empty", text=empty_text)
        self.library_count_var.set(f"{job_count} 个作业")
        self._update_action_states()

    def selected_library_path(self) -> Path | None:
        selected = self.library_tree.selection()
        return self.job_paths.get(selected[0]) if selected else None

    def add_selected_job(self) -> None:
        if self._is_running():
            return
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
                self.append_log(f"跳过损坏作业 {path.name}：{error}")
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
        self.queue_count_var.set(f"{len(self.queue)} 项")
        if select is not None and 0 <= select < len(self.queue):
            item_id = str(select)
            self.queue_tree.selection_set(item_id)
            self.queue_tree.focus(item_id)
            self.queue_tree.see(item_id)
        self._update_action_states()

    def selected_queue_index(self) -> int | None:
        selected = self.queue_tree.selection()
        return int(selected[0]) if selected else None

    def remove_queue_item(self) -> None:
        if self._is_running():
            return
        index = self.selected_queue_index()
        if index is None:
            return
        del self.queue[index]
        self.refresh_queue(select=min(index, len(self.queue) - 1))

    def clear_queue(self) -> None:
        if self._is_running():
            return
        self.queue.clear()
        self.refresh_queue()

    def move_queue(self, offset: int) -> None:
        if self._is_running():
            return
        index = self.selected_queue_index()
        if index is None:
            return
        target = index + offset
        if not 0 <= target < len(self.queue):
            return
        self.queue[index], self.queue[target] = self.queue[target], self.queue[index]
        self.refresh_queue(select=target)

    def clear_log(self) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def append_log(self, message: str) -> None:
        def update() -> None:
            if self._closing:
                return
            try:
                self.log_text.configure(state=tk.NORMAL)
                self.log_text.insert(tk.END, message + "\n")
                self.log_text.see(tk.END)
                self.log_text.configure(state=tk.DISABLED)
            except tk.TclError:
                pass

        if self._closing:
            return
        if threading.current_thread() is threading.main_thread():
            update()
            return
        try:
            self.after(0, update)
        except tk.TclError:
            pass

    def start_execution(self) -> None:
        if self._is_running():
            return
        if not self.queue:
            messagebox.showinfo("执行队列为空", "请先从作业库加入至少一个作业。", parent=self)
            return
        device = self.device_var.get().strip()
        if not device:
            messagebox.showwarning("没有设备", "请先在顶部设备栏选择 ADB 设备。", parent=self)
            return

        execution_queue = list(self.queue)
        self.stop_requested = False
        self.status_var.set("执行中")
        self.progress_var.set(f"准备执行 {len(execution_queue)} 项作业")
        self.append_log(f"\n开始执行队列 · 设备 {device}")
        self.worker = threading.Thread(
            target=self._run_queue,
            args=(execution_queue, device),
            daemon=True,
        )
        self._set_running_controls(True)
        self.worker.start()

    def _run_queue(self, execution_queue: list[Path], device: str) -> None:
        total = len(execution_queue)
        completed = 0
        try:
            for index, path in enumerate(execution_queue, start=1):
                if self.stop_requested:
                    break
                document = JobDocument.load(path)
                self._schedule_ui(lambda i=index, n=document.name: self.progress_var.set(f"{i}/{total} · {n}"))
                self.append_log(f"\n[{index}/{total}] 开始：{document.name}")
                succeeded = self.runner.run(document, device, self.append_log)
                if not succeeded:
                    self.append_log(f"失败：{document.name}")
                    break
                completed += 1
                self.append_log(f"完成：{document.name}")
        except Exception as error:
            self.append_log(f"执行异常：{error}")
        finally:
            stopped = self.stop_requested
            self._schedule_ui(lambda: self._execution_finished(completed, total, stopped))

    def _schedule_ui(self, callback: Callable[[], None]) -> None:
        if self._closing:
            return
        try:
            self.after(0, callback)
        except tk.TclError:
            pass

    def _execution_finished(self, completed: int, total: int, stopped: bool) -> None:
        if self._closing:
            return
        self.status_var.set("已停止" if stopped else ("执行完成" if completed == total else "执行失败"))
        self.progress_var.set(f"完成 {completed}/{total}")
        self._set_running_controls(False)

    def stop_execution(self) -> None:
        if not self._is_running() or self.stop_requested:
            return
        self.stop_requested = True
        self.status_var.set("正在停止")
        self.progress_var.set("正在等待当前任务安全停止…")
        self.stop_button.configure(state=tk.DISABLED)
        threading.Thread(target=lambda: self.runner.stop(self.append_log), daemon=True).start()

    def _is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive())

    @staticmethod
    def _set_enabled(widget: ttk.Button, enabled: bool) -> None:
        widget.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    def _set_running_controls(self, running: bool) -> None:
        self.start_button.configure(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_button.configure(state=tk.NORMAL if running else tk.DISABLED)
        self._update_action_states(running)

    def _update_action_states(self, running: bool | None = None) -> None:
        if not hasattr(self, "add_button"):
            return
        if running is None:
            running = self._is_running()
        library_selected = self.selected_library_path() is not None
        queue_index = self.selected_queue_index()
        self._set_enabled(self.add_button, library_selected and not running)
        self._set_enabled(self.remove_button, queue_index is not None and not running)
        self._set_enabled(self.clear_button, bool(self.queue) and not running)
        self._set_enabled(self.move_up_button, queue_index is not None and queue_index > 0 and not running)
        self._set_enabled(
            self.move_down_button,
            queue_index is not None and queue_index < len(self.queue) - 1 and not running,
        )

    def _confirm_stop(self, prompt: str) -> bool:
        if not self._is_running() or self.stop_requested:
            return True
        if not messagebox.askyesno("作业正在执行", prompt, parent=self):
            return False
        self.stop_execution()
        return True

    def prepare_leave(self) -> bool:
        """Confirm and stop an active run before switching back to recording."""
        return self._confirm_stop("停止当前执行并返回步骤录制吗？")

    def can_leave(self) -> bool:
        """Compatibility alias for callers using the earlier panel contract."""
        return self.prepare_leave()

    def prepare_close(self) -> bool:
        """Confirm and stop an active run before the application closes."""
        if not self._confirm_stop("当前作业仍在执行，停止作业并退出程序吗？"):
            return False
        self._closing = True
        return True

    def back_to_editor(self) -> None:
        if not self.prepare_leave():
            return
        if self.on_record_requested is not None:
            self.on_record_requested()

    def destroy(self) -> None:
        self._closing = True
        if self._is_running() and not self.stop_requested:
            self.stop_requested = True
            threading.Thread(target=lambda: self.runner.stop(lambda _message: None), daemon=True).start()
        try:
            self.search_var.trace_remove("write", self._search_trace)
        except (AttributeError, tk.TclError):
            pass
        try:
            self.device_var.trace_remove("write", self._device_trace)
        except (AttributeError, tk.TclError):
            pass
        super().destroy()


# Import compatibility only. The runner is now a Frame and must be placed by its parent.
JobRunnerWindow = JobRunnerPanel
