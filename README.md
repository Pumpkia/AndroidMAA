# MaaQQLogin

MaaQQLogin 是基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 的 Android ADB 自动化用例工作台，面向 QQ App 等移动端场景。它在一个窗口中完成设备截图、用例录制、用例管理和队列回放。

## 环境要求

- Windows 10/11（64 位）
- Python 3.10 或更高版本
- 已安装 QQ App 的 Android 真机或模拟器
- 设备已开启开发者选项和 USB 调试，并完成 ADB 授权

项目自带 Windows `platform-tools`。也可以使用系统 `PATH` 中的 `adb`。

## 界面布局

- 顶部通过“用例录制”和“用例回放”在同一窗口内切换工作区。
- 左侧始终显示设备预览，可选择 ADB 设备、刷新设备列表并截图。录制模式还提供框选模板、点击位置和滑动轨迹工具。
- 右侧“用例录制”工作区用于编排步骤、设置识别与动作参数、管理用例库以及保存或导出用例。
- 右侧“用例回放”工作区用于搜索用例、编辑执行队列、开始或停止任务，并查看实时执行日志。

录制和回放共享当前设备、`jobs/` 用例库及 `assets/resource/image/jobs/` 模板库，切换工作区不会打开第二个主窗口。

## 源码运行

在项目根目录执行：

```powershell
python -m pip install -r tools/requirements.txt
python tools/qt_workbench.py
```

也可以双击 `job-editor.bat` 启动。

## 连接设备

1. 启动 Android 模拟器，或通过 USB 连接已开启调试的真机。
2. 在设备上接受 USB 调试授权。
3. 在项目根目录检查连接状态：

   ```powershell
   .\platform-tools\adb.exe devices
   ```

4. 确认设备状态为 `device`，而不是 `unauthorized` 或 `offline`。
5. 启动工作台，在左侧“ADB 设备”中选择设备，点击“刷新”，再点击“截图”。

## 基本使用

### 录制用例

1. 在顶部选择“用例录制”，新建用例或从“用例库”载入已有用例。
2. 获取设备截图后，在左侧选择“框选模板”“点击位置”或“滑动轨迹”，并在预览中完成标记。
3. 在右侧填写步骤名称，选择识别类型和动作类型，按需设置 OCR 文字、输入内容、阈值与延迟。
4. 将步骤加入列表，调整顺序，并使用“在设备上预览此动作”检查单步效果。
5. 点击“保存”。保存成功后会显示确认提示，步骤属性自动恢复为“新建步骤”状态，已保存的步骤列表不会清空。
6. 用例写入 `jobs/<分类>/`，模板写入 `assets/resource/image/jobs/<用例名>/`；需要 Maa Pipeline 文件时点击“导出”。

支持的识别类型包括 `TemplateMatch`、`OCR` 和 `DirectHit`；支持的动作类型包括 `Click`、`Swipe`、`InputText`、`ClickKey` 和 `DoNothing`。

### 回放用例

1. 在顶部选择“用例回放”。
2. 使用“新建分类”添加自定义分类；选中分类后可重命名或删除。
3. 将用例拖到目标分类即可移动目录，用例的分类字段和相关前置用例路径会同步更新。
4. 选中用例可加入执行队列、删除用例，或点击“编辑步骤”返回录制界面继续修改。
5. 使用“上移”“下移”“移除”调整队列，然后点击“开始执行”。
6. 运行期间用例库修改功能会禁用；可点击“停止”，并在日志中查看执行结果。

删除用例会显示确认提示；删除包含用例的分类需要二次确认，删除操作不可撤销。

## v2.1.0 更新说明

- 新增用例删除和分类级联删除。
- 新增自定义分类的创建、重命名和删除。
- 新增拖动用例切换目录分类，并同步前置用例路径。
- 新增从回放界面直接打开用例编辑步骤。
- 保存成功后显示确认，并恢复为新建步骤状态。
- 打包成功后自动清理临时目录，只保留 `dist/QQJobEditor/QQJobEditor.exe`。
- 本地用例、空分类及用例引用的模板会在更新程序时保留。

## 打包 Windows v2.1.0

在项目根目录执行：

```powershell
python -m pip install -r tools/requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_release.ps1 -Version v2.1.0
```

打包脚本会先运行单元测试，再使用 PyInstaller 生成发布 ZIP，并更新唯一的本地运行目录 `dist/QQJobEditor/`。构建使用的临时目录会在成功后自动删除，同时保留本地用例和用例引用的模板：

```text
release/QQJobEditor-v2.1.0-win-x64.zip
```

解压完整 ZIP 后运行 `QQJobEditor/QQJobEditor.exe`。不要只复制 EXE；`_internal/`、`assets/`、`jobs/` 和 `platform-tools/` 都是运行所需内容。

## 目录结构

```text
MaaQQLogin/
|-- assets/
|   |-- config/                       # MaaFramework 运行选项
|   `-- resource/
|       |-- image/jobs/               # 录制生成的模板图片
|       |-- model/ocr/                # OCR 模型与字符表
|       `-- pipeline/                 # 导出的 Pipeline
|-- jobs/                             # 用例 JSON 与分类目录
|-- platform-tools/                   # Windows ADB 运行时
|-- tools/
|   |-- qt_workbench.py               # Qt 主窗口、用例录制与回放
|   |-- job_runner_app.py             # 同窗用例回放工作区
|   |-- job_library.py                # 分类、移动与删除的安全文件操作
|   |-- job_runner.py                 # MaaFramework 执行器
|   |-- job_model.py                  # 用例模型与 Pipeline 导出
|   |-- build_release.ps1             # Windows 打包脚本
|   `-- requirements.txt              # Python 依赖
|-- QQJobEditor.spec                  # PyInstaller 配置
|-- job-editor.bat                    # 源码启动入口
`-- README.md
```

## 注意事项

- 截图和坐标按 MaaFramework 的短边 720 规则归一化；设备分辨率或 QQ 界面变化后应重新检查模板。
- `InputText` 内容会明文保存在用例 JSON 中，不要写入密码、Token 等敏感信息。
- 仅对自己拥有或获授权的设备和账号执行自动化任务。
