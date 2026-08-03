"""Embedded MaaFramework job runner used by the visual job editor."""

from __future__ import annotations

from pathlib import Path
import sys
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Callable

from job_library import JobLibrary
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
        on_edit_requested: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent, style="Panel.TFrame", padding=(16, 14))
        self.device_var = device_var
        self.on_record_requested = on_record_requested
        self.on_edit_requested = on_edit_requested
        self.runner = MaaJobRunner(APP_DIR, ASSETS_DIR, JOBS_DIR)
        self.library = JobLibrary(JOBS_DIR)
        self.job_paths: dict[str, Path] = {}
        self.category_names: dict[str, str] = {}
        self.queue: list[Path] = []
        self.stop_requested = False
        self.worker: threading.Thread | None = None
        self._closing = False
        self._drag_job_path: Path | None = None
        self._drag_start: tuple[int, int] | None = None
        self._drag_active = False

        self.search_var = tk.StringVar(master=self)
        self.status_var = tk.StringVar(master=self, value="就绪")
        self.progress_var = tk.StringVar(master=self, value="从作业库选择任务并加入执行队列")
        self.device_summary_var = tk.StringVar(master=self)
        self.library_count_var = tk.StringVar(master=self, value="0 个作业")
        self.queue_count_var = tk.StringVar(master=self, value="0 项")
        self.progress_value_var = tk.DoubleVar(master=self, value=0.0)

        self._build_ui()
        self._search_trace = self.search_var.trace_add("write", self._on_search_changed)
        self._device_trace = self.device_var.trace_add("write", self._on_device_changed)
        self._sync_device_summary()
        self.activate()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        content = tk.PanedWindow(
            self,
            orient=tk.HORIZONTAL,
            background="#D2D2D7",
            borderwidth=0,
            sashwidth=5,
            sashrelief=tk.FLAT,
            showhandle=False,
        )
        content.grid(row=1, column=0, sticky="nsew")

        library_panel = ttk.Frame(content, style="Panel.TFrame", padding=(0, 12, 12, 0))
        queue_panel = ttk.Frame(content, style="Panel.TFrame", padding=(12, 12, 12, 0))
        control_panel = ttk.Frame(content, style="Panel.TFrame", padding=(12, 12, 0, 0))
        content.add(library_panel, minsize=235, stretch="always")
        content.add(queue_panel, minsize=330, stretch="always")
        content.add(control_panel, minsize=255, stretch="always")

        self._build_library(library_panel)
        self._build_queue(queue_panel)
        self._build_control(control_panel)
        self._build_log(control_panel)

    def _build_header(self) -> None:
        header = ttk.Frame(self, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        title_group = ttk.Frame(header, style="Panel.TFrame")
        title_group.grid(row=0, column=0, sticky="w")
        ttk.Label(title_group, text="执行控制", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            title_group,
            textvariable=self.device_summary_var,
            style="Muted.TLabel",
            wraplength=300,
        ).pack(anchor=tk.W, pady=(3, 0))

        progress_group = ttk.Frame(header, style="Panel.TFrame")
        progress_group.grid(row=0, column=1, sticky="e", padx=(16, 20))
        progress_heading = ttk.Frame(progress_group, style="Panel.TFrame")
        progress_heading.pack(fill=tk.X)
        ttk.Label(progress_heading, text="执行进度", style="Muted.TLabel").pack(side=tk.LEFT)
        ttk.Label(progress_heading, textvariable=self.queue_count_var, style="Muted.TLabel").pack(side=tk.RIGHT)
        ttk.Progressbar(
            progress_group,
            variable=self.progress_value_var,
            maximum=100,
            length=180,
            style="Blue.Horizontal.TProgressbar",
        ).pack(fill=tk.X, pady=(5, 0))

        status_group = ttk.Frame(header, style="Panel.TFrame")
        status_group.grid(row=0, column=2, sticky="e")
        ttk.Label(status_group, text="当前状态", style="Muted.TLabel").pack(anchor=tk.E)
        ttk.Label(status_group, textvariable=self.status_var, style="StatusValue.TLabel").pack(anchor=tk.E, pady=(3, 0))

    def _build_library(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        section_header = ttk.Frame(parent, style="Panel.TFrame")
        section_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        section_header.columnconfigure(0, weight=1)
        ttk.Label(section_header, text="作业库", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(section_header, textvariable=self.library_count_var, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

        search_row = ttk.Frame(parent, style="Panel.TFrame")
        search_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        search_row.columnconfigure(0, weight=1)
        self.search_entry = ttk.Entry(search_row, textvariable=self.search_var)
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.search_entry.bind("<Return>", lambda _event: self.refresh_library())
        ttk.Button(search_row, text="刷新", command=self.refresh_library, style="Toolbar.TButton", width=6).grid(row=0, column=1, padx=(6, 0))

        manage_row = ttk.Frame(parent, style="Subtle.TFrame", padding=(6, 5))
        manage_row.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        manage_row.columnconfigure((0, 1), weight=1)
        self.new_category_button = ttk.Button(manage_row, text="新建分类", command=self.create_category, style="Toolbar.TButton")
        self.new_category_button.grid(row=0, column=0, sticky="ew", padx=(0, 3), pady=(0, 3))
        self.rename_category_button = ttk.Button(manage_row, text="重命名", command=self.rename_selected_category, style="Toolbar.TButton")
        self.rename_category_button.grid(row=0, column=1, sticky="ew", padx=(3, 0), pady=(0, 3))
        self.delete_library_button = ttk.Button(manage_row, text="删除", command=self.delete_selected_library_item, style="Danger.TButton")
        self.delete_library_button.grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=(3, 0))
        self.edit_job_button = ttk.Button(manage_row, text="编辑步骤", command=self.edit_selected_job, style="Toolbar.TButton")
        self.edit_job_button.grid(row=1, column=1, sticky="ew", padx=(3, 0), pady=(3, 0))

        tree_frame = ttk.Frame(parent, style="Panel.TFrame")
        tree_frame.grid(row=3, column=0, sticky="nsew")
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
        self.library_tree.bind("<Delete>", lambda _event: self.delete_selected_library_item())
        self.library_tree.bind("<F2>", lambda _event: self.rename_selected_category())
        self.library_tree.bind("<Control-e>", lambda _event: self.edit_selected_job())
        self.library_tree.bind("<Control-n>", lambda _event: self.create_category())
        self.library_tree.bind("<ButtonPress-1>", self._begin_library_drag, add="+")
        self.library_tree.bind("<B1-Motion>", self._track_library_drag, add="+")
        self.library_tree.bind("<ButtonRelease-1>", self._finish_library_drag, add="+")

        self.add_button = ttk.Button(parent, text="加入执行队列", command=self.add_selected_job, style="Primary.TButton")
        self.add_button.grid(row=4, column=0, sticky="ew", pady=(8, 0))

    def _build_queue(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        header = ttk.Frame(parent, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="执行队列", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, textvariable=self.queue_count_var, style="Muted.TLabel").grid(row=0, column=1, sticky="e")

        toolbar = ttk.Frame(parent, style="Subtle.TFrame", padding=(6, 5))
        toolbar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        toolbar.columnconfigure((0, 1, 2, 3), weight=1)
        self.remove_button = ttk.Button(toolbar, text="移除", command=self.remove_queue_item, style="Toolbar.TButton")
        self.remove_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.move_up_button = ttk.Button(toolbar, text="上移", command=lambda: self.move_queue(-1), style="Toolbar.TButton")
        self.move_up_button.grid(row=0, column=1, sticky="ew", padx=3)
        self.move_down_button = ttk.Button(toolbar, text="下移", command=lambda: self.move_queue(1), style="Toolbar.TButton")
        self.move_down_button.grid(row=0, column=2, sticky="ew", padx=3)
        self.clear_button = ttk.Button(toolbar, text="清空", command=self.clear_queue, style="Danger.TButton")
        self.clear_button.grid(row=0, column=3, sticky="ew", padx=(3, 0))

        tree_frame = ttk.Frame(parent, style="Panel.TFrame")
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        columns = ("index", "name", "category", "prerequisites")
        self.queue_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=5, selectmode="browse")
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

    def _build_control(self, parent: ttk.Frame) -> None:
        control = ttk.Frame(parent, style="Subtle.TFrame", padding=10)
        control.pack(fill=tk.X)
        ttk.Label(control, text="执行控制", style="Subtle.TLabel").pack(anchor=tk.W, pady=(0, 8))

        buttons = ttk.Frame(control, style="Subtle.TFrame")
        buttons.pack(fill=tk.X)
        buttons.columnconfigure((0, 1), weight=1)
        self.start_button = ttk.Button(buttons, text="开始执行", command=self.start_execution, style="Primary.TButton")
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        self.stop_button = ttk.Button(buttons, text="停止", command=self.stop_execution, style="Danger.TButton", state=tk.DISABLED)
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        ttk.Label(control, textvariable=self.progress_var, style="Subtle.TLabel", wraplength=250, justify=tk.LEFT).pack(fill=tk.X, pady=(9, 0))

    def _build_log(self, parent: ttk.Frame) -> None:
        log_section = ttk.Frame(parent, style="Panel.TFrame")
        log_section.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        log_section.columnconfigure(0, weight=1)
        log_section.rowconfigure(1, weight=1)

        header = ttk.Frame(log_section, style="Panel.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="执行日志", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="清空", command=self.clear_log, style="Toolbar.TButton", width=6).grid(row=0, column=1, sticky="e")

        log_frame = ttk.Frame(log_section, style="Panel.TFrame")
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = tk.Text(
            log_frame,
            state=tk.DISABLED,
            wrap=tk.WORD,
            background="#F2F2F7",
            foreground="#414755",
            relief=tk.FLAT,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground="#D2D2D7",
            padx=10,
            pady=9,
            font=("Consolas", 9),
            width=30,
            height=8,
        )
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
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

    def refresh_library(
        self,
        select_path: Path | None = None,
        select_category: str | None = None,
    ) -> None:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        if select_path is None and select_category is None:
            previous_path = self.selected_library_path()
            previous_category = self.selected_category_name()
        else:
            previous_path = select_path
            previous_category = select_category
        self.library_tree.delete(*self.library_tree.get_children())
        self.job_paths.clear()
        self.category_names.clear()

        category_info = {item.name: item for item in self.library.list_categories()}
        grouped: dict[str, list[tuple[str, Path]]] = {name: [] for name in category_info}
        for path in sorted(JOBS_DIR.rglob("*.maa_job.json")):
            try:
                document = JobDocument.load(path)
            except Exception:
                continue
            relative = path.relative_to(JOBS_DIR)
            physical_category = relative.parts[0] if len(relative.parts) > 1 else ""
            category = (
                physical_category
                if physical_category in category_info
                else (document.category or suggest_category(document.name, document.steps))
            )
            grouped.setdefault(category, []).append((document.name, path))

        query = self.search_var.get().strip().casefold()
        visible_groups: dict[str, list[tuple[str, Path]]] = {}
        for category, items in grouped.items():
            category_matches = bool(query and query in category.casefold())
            visible_items = [
                item for item in items if not query or category_matches or query in item[0].casefold()
            ]
            if not query or category_matches or visible_items:
                visible_groups[category] = visible_items

        preferred = {name: index for index, name in enumerate(SMART_CATEGORIES)}
        categories = sorted(visible_groups, key=lambda value: (preferred.get(value, 999), value.casefold()))
        job_count = 0
        for category_index, category in enumerate(categories):
            items = sorted(visible_groups[category], key=lambda item: item[0].casefold())
            parent_id = f"category_{category_index}"
            self.library_tree.insert("", tk.END, iid=parent_id, text=f"{category}  ({len(items)})", open=True)
            if category in category_info:
                self.category_names[parent_id] = category
            for job_index, (name, path) in enumerate(items):
                item_id = f"job_{category_index}_{job_index}"
                self.library_tree.insert(parent_id, tk.END, iid=item_id, text=name)
                self.job_paths[item_id] = path
                job_count += 1
        if not categories:
            empty_text = "没有匹配的作业或分类" if query else "作业库为空"
            self.library_tree.insert("", tk.END, iid="empty", text=empty_text)

        self.library_count_var.set(f"{job_count} 个作业 · {len(categories)} 个分类")
        self._restore_library_selection(previous_path, previous_category)
        self._update_action_states()

    def _restore_library_selection(
        self,
        path: Path | None,
        category: str | None,
    ) -> None:
        target_id = ""
        if path is not None:
            expected = path.resolve(strict=False)
            target_id = next(
                (item_id for item_id, item_path in self.job_paths.items() if item_path.resolve(strict=False) == expected),
                "",
            )
        if not target_id and category:
            target_id = next(
                (item_id for item_id, name in self.category_names.items() if name == category),
                "",
            )
        if target_id:
            self.library_tree.selection_set(target_id)
            self.library_tree.focus(target_id)
            self.library_tree.see(target_id)

    def selected_library_path(self) -> Path | None:
        selected = self.library_tree.selection()
        return self.job_paths.get(selected[0]) if selected else None

    def selected_category_name(self) -> str | None:
        selected = self.library_tree.selection()
        return self.category_names.get(selected[0]) if selected else None

    def add_selected_job(self) -> None:
        if self._is_running():
            return
        path = self.selected_library_path()
        if path is None:
            return
        self.queue.append(path)
        self.refresh_queue(select=len(self.queue) - 1)

    def create_category(self) -> None:
        if self._is_running():
            return
        name = simpledialog.askstring("新建分类", "分类名称", parent=self)
        if name is None:
            return
        try:
            created = self.library.create_category(name.strip())
        except Exception as error:
            self._show_library_error("新建分类失败", error)
            return
        self.search_var.set("")
        self.refresh_library(select_category=created.name)
        self._library_feedback(f"已新建分类：{created.name}")

    def rename_selected_category(self) -> None:
        if self._is_running():
            return
        category = self.selected_category_name()
        if category is None:
            return
        new_name = simpledialog.askstring("重命名分类", "新的分类名称", initialvalue=category, parent=self)
        if new_name is None or new_name.strip() == category:
            return
        try:
            result = self.library.rename_category(category, new_name.strip())
        except Exception as error:
            self._show_library_error("重命名分类失败", error)
            return
        moved_paths = {
            source.resolve(strict=False): destination
            for source, destination in result.moved_jobs
        }
        self.queue = [
            moved_paths.get(path.resolve(strict=False), path)
            for path in self.queue
        ]
        self.search_var.set("")
        self.refresh_queue()
        self.refresh_library(select_category=result.path.name)
        self._library_feedback(f"分类已重命名为 {result.path.name}，同步更新 {result.jobs_updated} 个作业")

    def delete_selected_library_item(self) -> None:
        if self._is_running():
            return
        path = self.selected_library_path()
        if path is not None:
            self._delete_job(path)
            return
        category = self.selected_category_name()
        if category is not None:
            self._delete_category(category)

    def _delete_job(self, path: Path) -> None:
        try:
            document = JobDocument.load(path)
            display_name = document.name
        except Exception:
            display_name = path.name
        if not messagebox.askyesno(
            "删除作业",
            f"确定永久删除作业“{display_name}”吗？\n此操作无法撤销。",
            parent=self,
        ):
            return
        try:
            deleted = self.library.delete_job(path)
        except Exception as error:
            self._show_library_error("删除作业失败", error)
            return
        deleted_resolved = deleted.resolve(strict=False)
        self.queue = [item for item in self.queue if item.resolve(strict=False) != deleted_resolved]
        self.refresh_queue()
        self.refresh_library(select_category=deleted.parent.name)
        self._library_feedback(f"已删除作业：{display_name}")

    def _delete_category(self, category: str) -> None:
        info = next((item for item in self.library.list_categories() if item.name == category), None)
        if info is None:
            self._show_library_error("删除分类失败", FileNotFoundError(f"找不到分类：{category}"))
            return
        if not messagebox.askyesno(
            "删除分类",
            f"确定删除分类“{category}”吗？",
            parent=self,
        ):
            return
        if info.job_count and not messagebox.askyesno(
            "再次确认删除",
            f"该分类包含 {info.job_count} 个作业。继续将永久删除分类中的全部文件，且无法撤销。",
            icon="warning",
            parent=self,
        ):
            return
        try:
            result = self.library.delete_category(category)
        except Exception as error:
            self._show_library_error("删除分类失败", error)
            return
        deleted_paths = {item.resolve(strict=False) for item in result.deleted_jobs}
        self.queue = [item for item in self.queue if item.resolve(strict=False) not in deleted_paths]
        self.refresh_queue()
        self.refresh_library()
        self._library_feedback(f"已删除分类 {category}，共删除 {result.jobs_deleted} 个作业")

    def edit_selected_job(self) -> None:
        if self._is_running():
            return
        path = self.selected_library_path()
        if path is None:
            return
        try:
            if self.on_edit_requested is not None:
                self.on_edit_requested(path)
            elif self.on_record_requested is not None:
                self.on_record_requested()
            else:
                messagebox.showwarning("无法编辑", "当前窗口没有配置步骤编辑入口。", parent=self)
                return
        except Exception as error:
            self._show_library_error("打开作业失败", error)

    def _begin_library_drag(self, event: tk.Event) -> None:
        if self._is_running():
            self._reset_library_drag()
            return
        item_id = self.library_tree.identify_row(event.y)
        self._drag_job_path = self.job_paths.get(item_id)
        self._drag_start = (event.x, event.y) if self._drag_job_path is not None else None
        self._drag_active = False

    def _track_library_drag(self, event: tk.Event) -> None:
        if self._drag_job_path is None or self._drag_start is None:
            return
        if not self._drag_active:
            start_x, start_y = self._drag_start
            self._drag_active = abs(event.x - start_x) + abs(event.y - start_y) >= 6
        if not self._drag_active:
            return
        target_id = self.library_tree.identify_row(event.y)
        if target_id in self.category_names:
            self.library_tree.selection_set(target_id)
            self.library_tree.focus(target_id)
            self.library_tree.configure(cursor="hand2")
        else:
            self.library_tree.configure(cursor="")

    def _finish_library_drag(self, event: tk.Event) -> None:
        source = self._drag_job_path
        dragged = self._drag_active
        target_id = self.library_tree.identify_row(event.y)
        category = self.category_names.get(target_id)
        self._reset_library_drag()
        if dragged and source is not None and category is not None and not self._is_running():
            self._move_job_to_category(source, category)
        elif source is not None:
            self._restore_library_selection(source, None)

    def _reset_library_drag(self) -> None:
        self._drag_job_path = None
        self._drag_start = None
        self._drag_active = False
        try:
            self.library_tree.configure(cursor="")
        except tk.TclError:
            pass

    def _move_job_to_category(self, source: Path, category: str) -> None:
        try:
            destination = self.library.move_job(source, category)
        except Exception as error:
            self._show_library_error("移动作业失败", error)
            self.refresh_library(select_path=source)
            return
        source_resolved = source.resolve(strict=False)
        self.queue = [
            destination if item.resolve(strict=False) == source_resolved else item
            for item in self.queue
        ]
        self.refresh_queue()
        self.refresh_library(select_path=destination)
        self._library_feedback(f"已移动作业：{destination.name} → {category}")

    def _library_feedback(self, message: str) -> None:
        self.status_var.set("作业库已更新")
        self.progress_var.set(message)
        self.append_log(f"作业库 · {message}")

    def _show_library_error(self, title: str, error: Exception) -> None:
        self.status_var.set("作业库操作失败")
        self.progress_var.set(str(error))
        messagebox.showerror(title, str(error), parent=self)

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
        self.progress_value_var.set(0.0)
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
                self._schedule_ui(lambda value=(index - 1) * 100 / total: self.progress_value_var.set(value))
                self.append_log(f"\n[{index}/{total}] 开始：{document.name}")
                succeeded = self.runner.run(document, device, self.append_log)
                if not succeeded:
                    self.append_log(f"失败：{document.name}")
                    break
                completed += 1
                self._schedule_ui(lambda value=index * 100 / total: self.progress_value_var.set(value))
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
        self.progress_value_var.set(completed * 100 / total if total else 0.0)
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
        job_selected = self.selected_library_path() is not None
        category_selected = self.selected_category_name() is not None
        queue_index = self.selected_queue_index()
        self._set_enabled(self.new_category_button, not running)
        self._set_enabled(self.rename_category_button, category_selected and not running)
        self._set_enabled(self.delete_library_button, (job_selected or category_selected) and not running)
        self._set_enabled(self.edit_job_button, job_selected and not running)
        self._set_enabled(self.add_button, job_selected and not running)
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
