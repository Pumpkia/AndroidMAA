"""奇迹暖暖资产工作区：衣橱分类、模板预览与刷关记忆。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from asset_model import ASSET_CATEGORIES, AssetLibrary, GameAsset
from clothing_memory import JOB_FARM, ClothingItem, ClothingLedger
from job_model import JobStep
from semantic_navigator import scan_device
from stage_model import parse_stage
from stage_navigator import goto_stage, recognize_stage_screen


class ClothingItemDialog(QDialog):
    def __init__(self, parent, title, categories, item=None, parent_name=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.name_edit = QLineEdit(item.name if item else "")
        self.category = QComboBox()
        self.category.setEditable(True)
        for name in categories:
            self.category.addItem(name)
        if item and item.category:
            self.category.setCurrentText(item.category)
        elif "连衣裙" in categories:
            self.category.setCurrentText("连衣裙")
        self.needed = QSpinBox()
        self.needed.setRange(1, 9999)
        self.needed.setValue(item.needed if item else 1)
        self.owned = QSpinBox()
        self.owned.setRange(0, 9999)
        self.owned.setValue(item.owned if item else 0)
        self.stage = QLineEdit(item.stage if item else "")
        self.stage.setPlaceholderText("例如 少女5-3")
        self.daily_limit = QSpinBox()
        self.daily_limit.setRange(1, 99)
        self.daily_limit.setValue(item.daily_limit if item else 3)
        form = QFormLayout()
        if parent_name:
            form.addRow("上级", QLabel(parent_name))
        form.addRow("衣服", self.name_edit)
        form.addRow("部位", self.category)
        form.addRow("需要件数", self.needed)
        form.addRow("已有件数", self.owned)
        form.addRow("刷关", self.stage)
        form.addRow("每日次数", self.daily_limit)
        save = QPushButton("保存")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def values(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "category": self.category.currentText().strip(),
            "needed": self.needed.value(),
            "owned": self.owned.value(),
            "stage": self.stage.text().strip(),
            "daily_limit": self.daily_limit.value(),
        }


class AssetPage(QWidget):
    def __init__(self, app, root: Path, memory_path: Path | None = None):
        super().__init__()
        self.app = app
        self.library = AssetLibrary(root)
        self.assets: list[GameAsset] = []
        path = memory_path or Path(app.module_registry.path).parent / "clothing_memory.json"
        self.ledger = ClothingLedger(path)
        tabs = QTabWidget()
        tabs.addTab(self.build_catalog(), "衣橱模板")
        tabs.addTab(self.build_memory(), "刷关记忆")
        tabs.addTab(self.build_stage(), "关卡")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(tabs)
        self.refresh()

    def build_catalog(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.build_list(), 34)
        layout.addWidget(self.build_preview(), 36)
        layout.addWidget(self.build_detail(), 30)
        return page

    def build_list(self):
        pane = QFrame()
        pane.setObjectName("devicePane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(16, 12, 16, 16)
        title = QLabel("衣橱资产")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        row = QHBoxLayout()
        self.category = QComboBox()
        self.category.addItem("全部分类", "")
        self.category.currentIndexChanged.connect(lambda _index: self.refresh())
        row.addWidget(self.category, 1)
        refresh = QPushButton("刷新")
        refresh.setProperty("compact", True)
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索资产名称")
        self.search.textChanged.connect(lambda _value: self.populate_table())
        layout.addWidget(self.search)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["名称", "分类", "大小"])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self.show_selected)
        layout.addWidget(self.table, 1)
        return pane

    def build_preview(self):
        pane = QFrame()
        pane.setObjectName("centerPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(16, 12, 16, 16)
        title = QLabel("资产预览")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.preview = QLabel("选择资产或保存当前截图")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setObjectName("selectionInfo")
        self.preview.setMinimumHeight(420)
        layout.addWidget(self.preview, 1)
        return pane

    def build_detail(self):
        pane = QFrame()
        pane.setObjectName("rightPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(16, 12, 16, 16)
        title = QLabel("资产信息")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.info = QLabel("尚未选择资产")
        self.info.setObjectName("selectionInfo")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.refs = QLabel("")
        self.refs.setObjectName("muted")
        self.refs.setWordWrap(True)
        layout.addWidget(self.refs)
        layout.addStretch()
        actions = QGridLayout()
        import_button = QPushButton("导入图片")
        import_button.clicked.connect(self.import_file)
        capture = QPushButton("从截图保存")
        capture.setObjectName("primaryButton")
        capture.clicked.connect(self.save_screenshot)
        delete = QPushButton("删除")
        delete.setProperty("danger", True)
        delete.clicked.connect(self.delete_selected)
        add = QPushButton("加入当前用例")
        add.setObjectName("primaryButton")
        add.clicked.connect(self.add_to_job)
        actions.addWidget(import_button, 0, 0)
        actions.addWidget(capture, 0, 1)
        actions.addWidget(delete, 1, 0)
        actions.addWidget(add, 1, 1)
        layout.addLayout(actions)
        hint = QLabel("资产写入 resource/image/assets/<分类>/，用例模板路径为 assets/<分类>/<文件名>。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return pane

    def build_memory(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.build_memory_tree(), 58)
        layout.addWidget(self.build_memory_form(), 42)
        return page

    def build_memory_tree(self):
        pane = QFrame()
        pane.setObjectName("centerPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(16, 12, 16, 16)
        title = QLabel("目标与材料")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.memory_summary = QLabel("当前没有待刷衣服")
        self.memory_summary.setObjectName("selectionInfo")
        self.memory_summary.setWordWrap(True)
        layout.addWidget(self.memory_summary)
        self.memory_tree = QTreeWidget()
        self.memory_tree.setHeaderLabels(["衣服", "层级", "已有", "可用", "关卡", "今日"])
        self.memory_tree.setAlternatingRowColors(True)
        self.memory_tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        header = self.memory_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.memory_tree.itemSelectionChanged.connect(self.load_memory_item)
        layout.addWidget(self.memory_tree, 1)
        buttons = QHBoxLayout()
        add_target = QPushButton("新建目标")
        add_target.setObjectName("primaryButton")
        add_target.clicked.connect(lambda: self.edit_memory_item(parent_id=""))
        add_material = QPushButton("添加材料")
        add_material.clicked.connect(self.add_memory_material)
        remove = QPushButton("删除")
        remove.setProperty("danger", True)
        remove.clicked.connect(self.delete_memory_item)
        buttons.addWidget(add_target)
        buttons.addWidget(add_material)
        buttons.addWidget(remove)
        layout.addLayout(buttons)
        return pane

    def build_memory_form(self):
        pane = QFrame()
        pane.setObjectName("rightPane")
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(16, 12, 16, 16)
        title = QLabel("记录")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.memory_name = QLineEdit()
        self.memory_category = QComboBox()
        self.memory_category.setEditable(True)
        for name in ASSET_CATEGORIES:
            self.memory_category.addItem(name)
        self.memory_needed = QSpinBox()
        self.memory_needed.setRange(1, 9999)
        self.memory_owned = QSpinBox()
        self.memory_owned.setRange(0, 9999)
        self.memory_stage = QLineEdit()
        self.memory_stage.setPlaceholderText("例如 公主12-3")
        self.memory_limit = QSpinBox()
        self.memory_limit.setRange(1, 99)
        self.memory_limit.setValue(3)
        self.memory_missing = QLabel("差 0 件")
        self.memory_missing.setObjectName("selectionInfo")
        self.memory_needed.valueChanged.connect(self.update_missing_label)
        self.memory_owned.valueChanged.connect(self.update_missing_label)
        form = QFormLayout()
        form.addRow("衣服", self.memory_name)
        form.addRow("部位", self.memory_category)
        form.addRow("需要", self.memory_needed)
        form.addRow("已有", self.memory_owned)
        form.addRow("缺口", self.memory_missing)
        form.addRow("刷哪关", self.memory_stage)
        form.addRow("每日次数", self.memory_limit)
        layout.addLayout(form)
        save = QPushButton("保存修改")
        save.clicked.connect(self.save_memory_item)
        gain = QPushButton("获得一件")
        gain.setObjectName("primaryButton")
        gain.clicked.connect(self.gain_memory_item)
        clear = QPushButton("通关一次")
        clear.setObjectName("primaryButton")
        clear.clicked.connect(self.clear_memory_stage)
        recognize = QPushButton("识别关卡")
        recognize.clicked.connect(self.recognize_stage)
        go = QPushButton("前往此关")
        go.setObjectName("primaryButton")
        go.clicked.connect(self.goto_memory_stage)
        layout.addWidget(save)
        layout.addWidget(gain)
        layout.addWidget(clear)
        layout.addWidget(recognize)
        layout.addWidget(go)
        hint = QLabel("目标衣服可继续添加下级材料。同一关卡共用今日通过次数，跨天自动清零。前往此关会点左下角切换章节，滑动列表，再点章节右侧任意进度（1/12、4/12、12/12 等）展开明细。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()
        return pane

    def build_stage(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        left = QFrame()
        left.setObjectName("centerPane")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 12, 16, 16)
        title = QLabel("当前界面")
        title.setObjectName("sectionTitle")
        left_layout.addWidget(title)
        self.stage_status = QLabel("点击识别关卡，读取切换章节列表和当前关卡。")
        self.stage_status.setObjectName("selectionInfo")
        self.stage_status.setWordWrap(True)
        left_layout.addWidget(self.stage_status)
        self.stage_tree = QTreeWidget()
        self.stage_tree.setHeaderLabels(["可见章节 / 关卡"])
        self.stage_tree.setAlternatingRowColors(True)
        self.stage_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(self.stage_tree, 1)
        right = QFrame()
        right.setObjectName("rightPane")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 12, 16, 16)
        form_title = QLabel("前往关卡")
        form_title.setObjectName("sectionTitle")
        right_layout.addWidget(form_title)
        self.stage_target = QLineEdit()
        self.stage_target.setPlaceholderText("例如 公主12-3 或 少女10-支2")
        right_layout.addWidget(QLabel("目标"))
        right_layout.addWidget(self.stage_target)
        recognize = QPushButton("识别当前界面")
        recognize.clicked.connect(self.recognize_stage)
        go = QPushButton("打开章节并进入")
        go.setObjectName("primaryButton")
        go.clicked.connect(self.goto_stage_target)
        right_layout.addWidget(recognize)
        right_layout.addWidget(go)
        hint = QLabel("流程：点左下角「切换章节」→ 上下滑动列表 → 点章节右侧任意 n/m 进度展开（左边完成数不固定）→ 再点具体关卡。未解锁章节不会进入。")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        right_layout.addWidget(hint)
        right_layout.addStretch()
        layout.addWidget(left, 58)
        layout.addWidget(right, 42)
        return page

    def refresh(self):
        current = self.category.currentData() if self.category.count() else ""
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("全部分类", "")
        for name in self.library.list_categories():
            self.category.addItem(name, name)
        index = self.category.findData(current)
        self.category.setCurrentIndex(index if index >= 0 else 0)
        self.category.blockSignals(False)
        selected = self.category.currentData() or None
        self.assets = self.library.list_assets(selected)
        self.populate_table()
        self.refresh_memory()

    def populate_table(self):
        query = self.search.text().strip().casefold()
        rows = [asset for asset in self.assets if query in asset.name.casefold() or query in asset.category.casefold()]
        self.table.setRowCount(len(rows))
        for index, asset in enumerate(rows):
            name = QTableWidgetItem(asset.name)
            name.setData(Qt.ItemDataRole.UserRole, asset.relative)
            self.table.setItem(index, 0, name)
            self.table.setItem(index, 1, QTableWidgetItem(asset.category))
            self.table.setItem(index, 2, QTableWidgetItem(self._size_label(asset.file_size)))
        if rows:
            self.table.selectRow(0)
        else:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("当前分类没有资产")
            self.info.setText("尚未选择资产")
            self.refs.setText("")

    def selected_asset(self) -> GameAsset | None:
        items = self.table.selectedItems()
        if not items:
            return None
        relative = self.table.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        for asset in self.assets:
            if asset.relative == relative:
                return asset
        return None

    def show_selected(self):
        asset = self.selected_asset()
        if asset is None:
            return
        pixmap = QPixmap(str(asset.path))
        if pixmap.isNull():
            self.preview.setPixmap(QPixmap())
            self.preview.setText("无法预览该图片")
        else:
            fitted = pixmap.scaled(
                self.preview.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.preview.setPixmap(fitted)
            self.preview.setText("")
        self.info.setText(
            f"{asset.name}\n分类：{asset.category}\n模板：{asset.relative}\n文件：{asset.path.name}"
        )
        references = self.library.find_references(self.app.module_registry.path.parent, asset.relative)
        if references:
            names = "、".join(path.stem.replace(".maa_job", "") for path in references[:6])
            extra = "" if len(references) <= 6 else f" 等 {len(references)} 个"
            self.refs.setText(f"被用例引用：{names}{extra}")
        else:
            self.refs.setText("尚未被用例引用")

    def import_file(self):
        category = self._ask_category()
        if not category:
            return
        value, _filter = QFileDialog.getOpenFileName(
            self,
            "导入奇迹暖暖资产",
            str(self.library.root),
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not value:
            return
        try:
            asset = self.library.import_file(Path(value), category)
        except Exception as error:
            QMessageBox.critical(self, "导入失败", str(error))
            return
        self.refresh()
        self._select_relative(asset.relative)
        self.app.toast(f"已导入资产 {asset.name}")

    def save_screenshot(self):
        image = getattr(self.app, "screen_image", None)
        if image is None:
            QMessageBox.warning(self, "从截图保存", "请先在顶部获取设备截图。")
            return
        category = self._ask_category("主界面")
        if not category:
            return
        name, ok = QInputDialog.getText(self, "从截图保存", "资产名称：", text="主界面")
        if not ok:
            return
        try:
            asset = self.library.save_image(image, category, name)
        except Exception as error:
            QMessageBox.critical(self, "保存失败", str(error))
            return
        self.refresh()
        self._select_relative(asset.relative)
        self.app.toast(f"已保存资产 {asset.name}")

    def delete_selected(self):
        asset = self.selected_asset()
        if asset is None:
            QMessageBox.warning(self, "删除资产", "请先选择要删除的资产。")
            return
        references = self.library.find_references(self.app.module_registry.path.parent, asset.relative)
        prompt = f"确定删除「{asset.name}」吗？此操作不可恢复。"
        if references:
            prompt += f"\n有 {len(references)} 个用例引用该模板。"
        if QMessageBox.question(self, "删除资产", prompt) != QMessageBox.StandardButton.Yes:
            return
        self.library.delete(asset)
        self.refresh()
        self.app.toast("资产已删除")

    def add_to_job(self):
        asset = self.selected_asset()
        if asset is None:
            QMessageBox.warning(self, "加入用例", "请先选择资产。")
            return
        module = self.app.module_registry.get("assets")
        step = JobStep(
            name=asset.name,
            recognition="TemplateMatch",
            action="Click",
            template=asset.relative,
        )
        errors = step.validate()
        if errors:
            QMessageBox.warning(self, "无法加入用例", "\n".join(errors))
            return
        if module is not None:
            self.app.document.module_id = module.id
            self.app.document.module_version = module.version
        self.app.document.steps.append(step)
        self.app.record.refresh_module_selection(self.app.document.module_id)
        self.app.record.refresh_steps(len(self.app.document.steps) - 1)
        self.app.set_dirty(True)
        self.app.switch_page(0)
        self.app.toast(f"已将 {asset.name} 加入当前用例")

    def refresh_memory(self):
        selected = self.selected_memory_id()
        self.ledger.ensure_today()
        self.memory_tree.clear()
        for item in self.ledger.roots():
            self.memory_tree.addTopLevelItem(self._memory_node(item))
        self.memory_tree.expandAll()
        self.memory_summary.setText(self.ledger.recommend())
        if selected:
            self._select_memory_id(selected)
        elif self.memory_tree.topLevelItemCount():
            self.memory_tree.setCurrentItem(self.memory_tree.topLevelItem(0))

    def _memory_node(self, item: ClothingItem) -> QTreeWidgetItem:
        remaining = self.ledger.remaining(item.stage) if item.stage else 0
        today = f"{self.ledger.used_today(item.stage)}/{item.daily_limit}" if item.stage else "--"
        piece = self.ledger.piece(item.id)
        usable = piece.consumable if piece is not None else max(0, item.owned - item.needed)
        node = QTreeWidgetItem(
            [
                item.name if not item.category else f"{item.name}（{item.category}）",
                self.ledger.layer_label(item.id),
                str(item.owned),
                str(usable),
                item.stage or "--",
                today if item.stage else "--",
            ]
        )
        node.setData(0, Qt.ItemDataRole.UserRole, item.id)
        if usable <= 0 and item.stage:
            node.setForeground(3, Qt.GlobalColor.darkRed)
        if item.stage and remaining <= 0:
            node.setForeground(4, Qt.GlobalColor.darkRed)
        for child in self.ledger.children_of(item.id):
            node.addChild(self._memory_node(child))
        return node

    def selected_memory_id(self) -> str:
        current = self.memory_tree.currentItem() if hasattr(self, "memory_tree") else None
        if current is None:
            return ""
        value = current.data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) else ""

    def load_memory_item(self):
        item = self.ledger.get(self.selected_memory_id())
        if item is None:
            return
        self.memory_name.setText(item.name)
        self.memory_category.setCurrentText(item.category or "连衣裙")
        self.memory_needed.setValue(item.needed)
        self.memory_owned.setValue(item.owned)
        self.memory_stage.setText(item.stage)
        if hasattr(self, "stage_target") and item.stage:
            self.stage_target.setText(item.stage)
        self.memory_limit.setValue(item.daily_limit)
        self.update_missing_label()

    def update_missing_label(self):
        missing = max(0, self.memory_needed.value() - self.memory_owned.value())
        self.memory_missing.setText(f"差 {missing} 件")

    def edit_memory_item(self, parent_id=""):
        parent = self.ledger.get(parent_id) if parent_id else None
        dialog = ClothingItemDialog(
            self,
            "添加材料" if parent else "新建目标",
            list(ASSET_CATEGORIES),
            parent_name=parent.name if parent else "",
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["name"]:
            QMessageBox.warning(self, "刷关记忆", "请填写衣服名称。")
            return
        try:
            item = self.ledger.add_item(parent_id=parent_id, **values)
        except Exception as error:
            QMessageBox.critical(self, "保存失败", str(error))
            return
        self.refresh_memory()
        self._select_memory_id(item.id)
        self.app.toast(f"已记录 {item.name}")

    def add_memory_material(self):
        parent_id = self.selected_memory_id()
        if not parent_id:
            QMessageBox.warning(self, "添加材料", "请先选择上级衣服。")
            return
        self.edit_memory_item(parent_id)

    def save_memory_item(self):
        item_id = self.selected_memory_id()
        item = self.ledger.get(item_id)
        if item is None:
            QMessageBox.warning(self, "保存修改", "请先选择衣服。")
            return
        updated = ClothingItem(
            id=item.id,
            name=self.memory_name.text().strip(),
            category=self.memory_category.currentText().strip(),
            needed=self.memory_needed.value(),
            owned=self.memory_owned.value(),
            stage=self.memory_stage.text().strip(),
            daily_limit=self.memory_limit.value(),
            parent_id=item.parent_id,
        )
        try:
            self.ledger.upsert(updated)
        except Exception as error:
            QMessageBox.critical(self, "保存失败", str(error))
            return
        self.refresh_memory()
        self._select_memory_id(item.id)
        self.app.toast("刷关记忆已保存")

    def gain_memory_item(self):
        item_id = self.selected_memory_id()
        if not item_id:
            QMessageBox.warning(self, "获得一件", "请先选择衣服。")
            return
        try:
            item = self.ledger.gain(item_id)
        except Exception as error:
            QMessageBox.critical(self, "记录失败", str(error))
            return
        self.refresh_memory()
        self._select_memory_id(item.id)
        self.app.toast(f"{item.name} 现有 {item.owned} 件，还差 {item.missing} 件")

    def clear_memory_stage(self):
        item = self.ledger.get(self.selected_memory_id())
        if item is None:
            QMessageBox.warning(self, "通关一次", "请先选择衣服。")
            return
        try:
            self.ledger.apply_job_success(JOB_FARM)
            remaining = int(self.ledger.daily.get("remain") or 0)
        except Exception as error:
            QMessageBox.warning(self, "通关一次", str(error))
            return
        self.refresh_memory()
        self._select_memory_id(item.id)
        self.app.toast(f"{item.stage} 已记录通关，今日剩余 {remaining} 次")

    def recognize_stage(self):
        if not self.app.adb.serial:
            QMessageBox.warning(self, "识别关卡", "请先选择已连接的 ADB 设备。")
            return
        serial = self.app.adb.serial
        session = self.app.adb.for_serial(serial)
        self.app.set_execution_active(True, "stage_scan")

        def done(state):
            self.app.set_execution_active(False)
            if self.app.adb.serial != serial:
                self.app.toast("设备已切换，已丢弃识别结果")
                self.app.finish_close_if_requested()
                return
            self._show_stage_state(state)
            self.app.finish_close_if_requested()

        def failed(error):
            self.app.set_execution_active(False)
            QMessageBox.critical(self, "识别关卡失败", error)
            self.app.finish_close_if_requested()

        self.app.run_async(lambda: recognize_stage_screen(scan_device(session)), done, failed)

    def goto_memory_stage(self):
        self.stage_target.setText(self.memory_stage.text().strip())
        self.goto_stage_target()

    def goto_stage_target(self):
        raw = self.stage_target.text().strip() or self.memory_stage.text().strip()
        try:
            target = parse_stage(raw)
        except ValueError as error:
            QMessageBox.warning(self, "前往关卡", str(error))
            return
        if not self.app.adb.serial:
            QMessageBox.warning(self, "前往关卡", "请先选择已连接的 ADB 设备。")
            return
        serial = self.app.adb.serial
        session = self.app.adb.for_serial(serial)
        self.stage_target.setText(target.canonical)
        self.app.set_execution_active(True, "stage_nav")

        def operation():
            return goto_stage(session, target, emit=lambda message: self.app.call_ui(lambda: self.app.toast(message)))

        def done(state):
            self.app.set_execution_active(False)
            self._show_stage_state(state)
            self.app.toast(f"已到达 {target.canonical}")
            self.app.finish_close_if_requested()

        def failed(error):
            self.app.set_execution_active(False)
            QMessageBox.critical(self, "前往关卡失败", error)
            self.app.finish_close_if_requested()

        self.app.run_async(operation, done, failed)

    def _show_stage_state(self, state):
        remaining = ""
        if state.remaining:
            remaining = f"，今日剩余 {state.remaining[0]}/{state.remaining[1]}"
        ref = state.stage_ref
        if ref is not None:
            self.memory_stage.setText(ref.canonical)
            self.stage_target.setText(ref.canonical)
        self.stage_status.setText(
            f"{state.kind}  {state.difficulty or '未识别难度'}  {state.title or '无标题'}{remaining}"
        )
        self.stage_tree.clear()
        for chapter in state.visible_chapters:
            item = QTreeWidgetItem([chapter + ("（未解锁）" if chapter in state.locked_chapters else "")])
            if chapter == state.expanded_chapter:
                for stage in state.visible_stages:
                    item.addChild(QTreeWidgetItem([stage]))
            self.stage_tree.addTopLevelItem(item)
        self.stage_tree.expandAll()
        if ref is not None:
            self.app.toast(f"当前 {ref.canonical}{remaining}")
        elif state.title:
            self.app.toast(f"当前 {state.title}")

    def delete_memory_item(self):
        item = self.ledger.get(self.selected_memory_id())
        if item is None:
            QMessageBox.warning(self, "删除", "请先选择衣服。")
            return
        children = self.ledger.children_of(item.id)
        prompt = f"确定删除「{item.name}」吗？"
        if children:
            prompt += f"\n将同时删除 {len(children)} 个下级材料。"
        if QMessageBox.question(self, "删除记忆", prompt) != QMessageBox.StandardButton.Yes:
            return
        self.ledger.remove(item.id)
        self.refresh_memory()
        self.app.toast("已删除刷关记录")

    def _select_memory_id(self, item_id: str) -> None:
        for row in range(self.memory_tree.topLevelItemCount()):
            found = self._find_memory_item(self.memory_tree.topLevelItem(row), item_id)
            if found is not None:
                self.memory_tree.setCurrentItem(found)
                return

    def _find_memory_item(self, node: QTreeWidgetItem, item_id: str) -> QTreeWidgetItem | None:
        if node.data(0, Qt.ItemDataRole.UserRole) == item_id:
            return node
        for index in range(node.childCount()):
            found = self._find_memory_item(node.child(index), item_id)
            if found is not None:
                return found
        return None

    def _ask_category(self, default: str = "") -> str:
        current = self.category.currentData() or default or ASSET_CATEGORIES[0]
        name, ok = QInputDialog.getItem(
            self,
            "选择分类",
            "衣橱分类：",
            self.library.list_categories(),
            max(0, self.library.list_categories().index(current)) if current in self.library.list_categories() else 0,
            True,
        )
        if not ok:
            return ""
        return name.strip()

    def _select_relative(self, relative: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == relative:
                self.table.selectRow(row)
                return

    @staticmethod
    def _size_label(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"
