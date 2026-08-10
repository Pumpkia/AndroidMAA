# Qdd

Qdd 是基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 的 Android ADB 自动化用例工作台，面向 QQ App 等移动端场景。它在一个窗口中完成设备截图、用例录制、用例管理、队列回放和命名区域的语义导航。

## 环境要求

- Windows 10/11（64 位）或 macOS 13 及更高版本
- Python 3.10 或更高版本
- 已安装 QQ App 的 Android 真机或模拟器
- 设备已开启开发者选项和 USB 调试，并完成 ADB 授权

Windows 发布包内置 Windows `platform-tools`，macOS 发布包内置 Darwin 版本；源码运行也可以使用系统 `PATH` 中的 `adb`。

## 界面布局

- 顶部通过“用例录制”“用例回放”和“语义导航”在同一窗口内切换工作区。
- 录制和回放工作区左侧显示设备预览；顶部可选择 ADB 设备、刷新设备列表并截图。录制模式还提供框选模板、点击位置和滑动轨迹工具，语义导航则使用控件区域列表完成命名和定位。
- “用例录制”页在中间提供截图标记画布，在右侧编排步骤、设置参数，并打开、保存或导出用例。
- 右侧“用例回放”工作区用于搜索用例、编辑执行队列、开始或停止任务，并查看实时执行日志。
- “语义导航”页扫描真机的资源 ID、无障碍描述和文字区域，可预览文字框与实际点击区域，并执行自然语言点击、检查或识别命令。

三个工作区共享当前设备和 `jobs/` 运行数据，切换工作区不会打开第二个主窗口。

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
5. 启动工作台，在顶部“ADB 设备”中选择设备，点击刷新图标，再点击“截图”。

## 基本使用

### 录制用例

1. 在顶部选择“用例录制”，新建用例或从“用例库”载入已有用例。
2. 获取设备截图后，在中间画布上方选择“框选识别区”“点击位置”或“滑动轨迹”，并在预览中完成标记。
3. 在右侧填写步骤名称，选择识别类型和动作类型，按需设置 OCR 文字、输入内容、阈值与延迟。
4. 将步骤加入列表，调整顺序，并使用“在设备上预览此动作”检查单步效果。
5. 点击“保存到用例库”。保存成功后会显示确认提示，当前步骤属性和步骤列表保持不变，可以继续编辑。
6. 用例写入 `jobs/<分类>/`，模板写入 `assets/resource/image/jobs/<用例名>/`；需要 Maa Pipeline 文件时点击“导出”。

录制截图会先按短边 720 归一化，再进入标记画布；识别区域、动作坐标和模板裁图均使用同一 Maa 坐标系。在设备上预览录制动作时，坐标会换算回当前设备的物理分辨率。

支持的识别类型包括 `TemplateMatch`、`OCR` 和 `DirectHit`；支持的动作类型包括 `Click`、`Swipe`、`InputText`、`ClickKey` 和 `DoNothing`。

### 回放用例

1. 在顶部选择“用例回放”。
2. 在用例库中搜索并选择用例；双击用例或点击“添加到执行队列”。
3. 选中用例后可点击“编辑”返回录制界面，或点击“删除”永久删除该用例文件。
4. 使用“上移”“下移”“移除”或“清空”调整队列，然后点击“开始执行”。
5. 按需启用“失败自动重试”和“失败时保存设备截图”，再开始执行。
6. 执行期间可点击“停止执行”，并在右侧查看每项状态、实时日志和完成进度。

回放开始时会绑定当时选中的 ADB 设备，并锁定设备选择、刷新、截图、录制页、用例库和队列编辑，直到任务结束或停止。失败自动重试最多执行一次；最终失败会停止整个队列，尚未执行的队列项标记为“已跳过”；失败截图写入 `logs/failures/`。

分类来自用例的“分类”字段和 `jobs/<分类>/` 目录。当前 Qt 工作台不提供分类新建、重命名、级联删除或拖动迁移功能。删除用例会显示确认提示且不可撤销。

### 语义导航

1. 在顶部选择“语义导航”，填写当前页面名称并点击“扫描当前界面”。
2. 单击候选行预览文字框和实际点击区域；可用“试点选中区域”验证真机落点，再填写区域名称和可选别名。
3. 用途可选择“点击”“检查”或“识别”；只有点击用途可填写“点击后页面”。检查或识别失败会立即中止后续步骤。保存结果写入 `jobs/semantic_map.json`。
4. 输入“点击搜索”“打开设置”等命令并选择“添加为用例步骤”。生成结果可直接保存到用例库、转到“用例录制”继续编辑，或在设备上预览。

语义扫描和“试点选中区域”开始时会绑定当时选中的设备，并暂时锁定设备选择与刷新，操作完成后再恢复。

生成命令会根据“点击后页面”关系加入跨页面路径。语义地图和生成的语义步骤会同时保存 OCR 文字区域与独立点击区域的归一化比例；回放时绑定启动设备，先将目标画面按短边 720 归一化，再依据该设备的实际纵横比把比例物化为 ROI 和点击区域，因此跨纵横比设备不会沿用源设备的固定像素框。点击步骤先识别文字，再点击独立区域；检查和识别步骤只验证内容。任何必需内容识别失败都不会执行 `next`。实时语义执行会在当前设备重新匹配界面结构并使用可点击父区域，不会按旧坐标盲点。

## v2.1.0 当前能力

- 在同一个 Qt 主窗口中完成用例录制、用例库浏览、执行队列和回放日志查看。
- 支持从回放界面直接打开用例并返回录制界面编辑步骤。
- 支持逐项执行状态、失败后单次重试和失败设备截图。
- 支持真机控件扫描、双坐标预览、区域命名，以及跨页面点击、检查和识别。
- 支持删除单个用例；分类管理和拖动迁移暂未在当前 Qt 工作台中提供。
- 打包成功后自动清理临时目录，并更新 Windows `dist/Qdd/` 或 macOS `dist/Qdd.app` 中的完整可运行目录。
- ZIP/DMG 使用空用例仓库生成，不包含旧用例、语义地图或录制截图；重建完成后的本地运行目录会保留原有用例及其引用模板。

## MAA 兼容性

`assets/interface.json` 遵循 MaaFramework ProjectInterface v2，`assets/resource/pipeline/` 使用当前 Pipeline Schema。兼容的 MAA 通用 UI 可通过“QQ账号”和“QQ密码”选项覆盖登录节点；这些输入可能由客户端明文保存，只应用于测试账号。

修改 ProjectInterface 或 Pipeline 后运行：

```powershell
python tools/validate_schema.py
```
## 打包发布包

Windows 和 macOS 发布包需要在对应系统上构建；PyInstaller 不建议跨系统交叉打包。

### Windows v2.1.0

在 Windows 项目根目录执行：

```powershell
python -m pip install -r tools/requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_release.ps1 -Version v2.1.0
```

打包脚本会先校验 ProjectInterface 和 Pipeline Schema，再运行单元测试，最后使用 PyInstaller 生成发布 ZIP，并更新唯一的本地运行目录 `dist/Qdd/`。构建使用的临时目录会在成功后自动删除，同时保留本地用例和用例引用的模板：

```text
release/Qdd-v2.1.0-win-x64.zip
```

解压完整 ZIP 后运行 `Qdd/Qdd.exe`。不要只复制 EXE；`_internal/`、`assets/`、`jobs/` 和 `platform-tools/` 都是运行所需内容。

### macOS v2.1.0

在 macOS 项目根目录执行：

```bash
python3 -m pip install -r tools/requirements.txt
curl -L --fail --output /tmp/platform-tools-latest-darwin.zip https://dl.google.com/android/repository/platform-tools-latest-darwin.zip
unzip -q -o /tmp/platform-tools-latest-darwin.zip -d /tmp
python3 tools/build_release_macos.py --version v2.1.0 --platform-tools /tmp/platform-tools
```

脚本会校验 Schema、运行单元测试、使用 PyInstaller 生成 `.app`，再生成 ZIP 和 DMG：

ZIP 和 DMG 始终使用空用例仓库；归档完成后，脚本才把现有 `dist/Qdd.app` 中的用例和安全引用模板恢复到新的本地应用并重新签名。

```text
release/Qdd-v2.1.0-macos-arm64.zip
release/Qdd-v2.1.0-macos-arm64.dmg
```

macOS 包内置 Darwin `platform-tools/adb`。没有 Apple Developer ID 证书时，脚本会使用本地 ad-hoc 签名；首次打开仍可能需要右键应用并选择“打开”。

### GitHub Actions 双系统构建

推送 `v*` 标签，或在 GitHub Actions 手动运行 `Build release packages` 工作流，会分别在 Windows 和 macOS runner 上构建并上传两个系统的包：

```bash
git tag v2.1.0
git push origin v2.1.0
```

## 目录结构

```text
Qdd/
|-- assets/
|   |-- config/                       # MaaFramework 运行选项
|   `-- resource/
|       |-- image/jobs/               # 录制生成的模板图片
|       |-- model/ocr/                # OCR 模型与字符表
|       `-- pipeline/                 # 导出的 Pipeline
|-- jobs/                             # 用例 JSON 与分类目录
|   `-- semantic_map.json             # 页面、命名区域与导航关系
|-- platform-tools/                   # 当前系统的 ADB 运行时
|-- tools/
|   |-- qt_workbench.py               # Qt 主窗口、用例录制与回放
|   |-- semantic_navigator.py         # 控件扫描、语义地图与路径执行
|   |-- job_editor.py                 # 旧版 Tk 用例录制界面
|   |-- job_runner_app.py             # 旧版 Tk 回放界面
|   |-- job_library.py                # 分类、移动与删除的安全文件操作
|   |-- job_runner.py                 # MaaFramework 执行器
|   |-- job_model.py                  # 用例模型与 Pipeline 导出
|   |-- validate_schema.py            # MAA Schema 校验
|   |-- build_release.ps1             # Windows 打包脚本
|   |-- build_release_macos.py        # macOS 打包脚本
|   `-- requirements.txt              # Python 依赖
|-- Qdd.spec                          # Windows PyInstaller 配置与应用图标
|-- Qdd.macos.spec                    # macOS PyInstaller 配置与应用图标
|-- AGENTS.md                         # Codex 项目规则与验证命令
|-- job-editor.bat                    # 源码启动入口
|-- 界面功能说明.md                    # 当前 Qt 界面的详细操作说明
`-- README.md
```

## 注意事项

- 用例录制截图、坐标和模板裁图按 MaaFramework 的短边 720 规则归一化；语义步骤另存区域比例，并在回放时按目标设备短边 720 后的实际纵横比重新物化。目标 App 布局明显变化后仍应重新检查录制模板。
- `InputText` 和 ProjectInterface 输入可能被明文保存，不要写入生产账号密码、Token 等敏感信息。
- 语义地图会保存用户填写的页面名、区域名和界面定位特征，不要把账号密码写入这些名称或别名。
- 仅对自己拥有或获授权的设备和账号执行自动化任务。
