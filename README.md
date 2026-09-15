# NnMaa

NnMaa 是基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 的 Android ADB 自动化用例工作台，面向《奇迹暖暖》等手游场景。它在一个窗口中完成设备截图、用例录制、用例管理、队列回放和衣橱资产管理。

## 环境要求

- Windows 10/11（64 位）
- Python 3.10 或更高版本
- 已安装《奇迹暖暖》的 Android 真机或模拟器
- 设备已开启开发者选项和 USB 调试，并完成 ADB 授权

Windows 环境已内置 `platform-tools`；如需在任意目录直接使用 `adb`，可把它加入 `PATH`。

## 界面布局

- 顶部通过“用例录制”“用例回放”和“资产”在同一窗口内切换工作区。
- 工作区左侧固定投屏；顶部可选择 ADB 设备、刷新设备列表并截图。录制模式还提供框选模板、点击位置和滑动轨迹工具。
- “用例录制”页在中间提供截图标记画布，在右侧编排步骤、设置参数，并打开、保存或导出用例。
- “用例回放”工作区用于搜索用例、编辑执行队列、开始或停止任务，并查看实时执行日志。
- “资产”页按奇迹暖暖衣橱分类管理模板图，可导入图片、保存当前截图，并把资产加入当前用例。

三个工作区共享当前设备和同一套用例数据，切换工作区不会打开第二个主窗口。数据的实际位置取决于安装版、便携版或源码运行模式，见“数据目录与迁移”。

## 源码运行

在项目根目录执行：

```powershell
python -m pip install -r tools/requirements.txt
python tools/qt_workbench.py
```

打包版直接双击 `NnMaa.exe`。命令行参数：

```powershell
NnMaa.exe                                    # 启动图形工作台
NnMaa.exe --run                              # 无界面执行默认 Pipeline 任务（StartNikki）
NnMaa.exe --run <任务名>                      # 指定 Pipeline 入口节点
NnMaa.exe --run <任务名> --serial <序列号>     # 指定 ADB 设备
NnMaa.exe --help
NnMaa.exe --version
```

scrcpy 投屏固定在工作台左侧，用例录制、回放和资产三个工作区共用。选设备后点「投屏录制」或「接入投屏」。需 scrcpy 2.4+。

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
3. 在右侧填写步骤名称，选择识别类型和动作类型，按需设置 OCR 文字、输入内容、阈值与延迟。OCR 可点「MAA识别」，用 MaaFramework 自带模型识别框选区域。
4. 将步骤加入列表，调整顺序，并使用“在设备上预览此动作”检查单步效果。
5. 点击“保存到用例库”。保存成功后会显示确认提示，当前步骤属性和步骤列表保持不变，可以继续编辑。
6. 用例和模板写入当前模式的数据目录；需要 Maa Pipeline 文件时点击“导出”。具体路径见“数据目录与迁移”。

录制截图会先按短边 720 归一化，再进入标记画布；识别区域、动作坐标和模板裁图均使用同一 Maa 坐标系。在设备上预览录制动作时，坐标会换算回当前设备的物理分辨率。
录制页的“模块”下拉框决定用例归属。新建用例默认绑定“用例录制”。可以在“新建/编辑模块”中创建自定义模块，定义模块 ID、规则版本、允许的用途和动作（点击、滑动、输入文本、按键、等待）。模块 ID 只能使用小写字母开头的 2-64 位字母、数字、下划线或短横线；模块至少允许一种用途和一种动作，内置模块不可覆盖。

保存和回放前会校验模块是否存在、已启用、版本是否匹配，以及每一步是否符合模块规则。停用、未知或版本不匹配的模块不会被静默执行；需要在录制页显式选择有效模块或更新规则版本后再保存。


支持的识别类型包括 `TemplateMatch`、`OCR` 和 `DirectHit`；支持的动作类型包括 `Click`、`Swipe`、`InputText`、`ClickKey` 和 `DoNothing`。



### 回放用例

1. 在顶部选择“用例回放”。
2. 在用例库中搜索并选择用例；双击用例或点击“添加到执行队列”。

3. 选中用例后可点击“编辑”返回录制界面，或点击“删除”永久删除该用例文件。
4. 使用“上移”“下移”“移除”或“清空”调整队列，然后点击“开始执行”。
5. 按需启用“失败自动重试”和“失败时保存设备截图”，再开始执行。
6. 执行期间可点击“停止执行”，并在右侧查看每项状态、实时日志和完成进度。
同一个用例只能在队列中出现一次。开始执行前会一次性检查队列文件、模块绑定和前置用例；检查失败时不会触碰设备，失败项及后续项会明确标记。


回放开始时会绑定当时选中的 ADB 设备，并锁定设备选择、刷新、截图、录制页、用例库和队列编辑，直到任务结束或停止。失败自动重试最多执行一次；最终失败会停止整个队列，尚未执行的队列项标记为“已跳过”；失败截图写入当前数据目录的 `logs/failures/`。

分类来自用例的“分类”字段和 `jobs/<分类>/` 目录。当前 Qt 工作台不提供分类新建、重命名、级联删除或拖动迁移功能。删除用例会显示确认提示且不可撤销。

### 资产管理

1. 在顶部选择“资产”，按发型、连衣裙、主界面等分类浏览模板。
2. 点击“导入图片”把衣橱或界面截图写入当前模式的 `resource/image/assets/<分类>/`。
3. 获取设备截图后，可点击“从截图保存”把当前画面收入衣橱分类。
4. 选中资产后点击“加入当前用例”，会生成模板匹配步骤并切换到“用例录制”；该用例绑定内置“资产”模块。
5. 打开“刷关记忆”页，新建目标衣服，再为它添加下级材料；记录需要件数、已有件数、刷哪关和每日通过次数。
6. 衣服账本只在 `jobs/clothing_memory.json`。人改 `have` / 每日次数；回放成功后短任务回调写入。Excel 不进脚本。
7. 仓库元任务 `warehouse_nz_rare` 只按记忆缺口挑选 `nav_8z3` / `farm_8z3_once` / `evo_base_to_hua` / `evo_hua_to_rare`。关卡号用 `8-支3` 这种支线格式。
8. “关卡”页可识别当前章节界面，并按「切换章节 → 滑动列表 → 点章节右侧任意 n/m 进度展开 → 点具体关卡」进入目标关。左边完成数不固定。

## v2.1.0 当前能力

- 在同一个 Qt 主窗口中完成用例录制、用例库浏览、执行队列、回放日志、衣橱资产和刷关记忆。
- 支持从回放界面直接打开用例并返回录制界面编辑步骤。
- 支持逐项执行状态、失败后单次重试和失败设备截图。
- 支持删除单个用例；分类管理和拖动迁移暂未在当前 Qt 工作台中提供。
- Windows 构建同时生成便携 ZIP 和 Inno Setup 安装程序；安装版可放在 `Program Files`，可写数据独立保存到当前用户目录。
- ????????????????? Windows `dist/NnMaa/` ??????????
- ZIP、Setup 和 DMG 使用空用例仓库生成，不包含旧用例或录制截图；重建完成后的本地运行目录会保留原有用例及其引用模板。


## 数据目录与迁移

NnMaa 将程序资源与可写数据分开。Windows 安装版可以安全安装到 `Program Files`，保存用例时不需要管理员权限。

| 运行方式 | 可写数据根目录 | 说明 |
| --- | --- | --- |
| Windows 安装版 | `%LOCALAPPDATA%\NnMaa` | Setup 不包含 `portable.flag`；升级和卸载不会删除此目录。 |
| Windows 便携 ZIP / `dist/NnMaa` | NnMaa 程序目录 | ZIP 和本地 `dist` 带 `portable.flag`，适合整体移动。 |
| Windows 源码运行 | 项目根目录 | 保持现有开发目录结构。 |

Windows 安装版的数据子目录如下：

```text
%LOCALAPPDATA%\NnMaa\
|-- jobs\                              # 用例、分类和 clothing_memory.json
|-- resource\image\jobs\               # 录制模板图片
|-- resource\image\assets\             # 奇迹暖暖衣橱与界面资产
|-- logs\failures\                     # 失败截图
|-- exports\                           # 默认 Pipeline 导出目录
`-- debug\                             # MaaFramework 运行日志
```

便携版和源码运行使用相同的 `jobs/`、`logs/` 与 `exports/` 相对位置，录制模板位于 `assets/resource/image/jobs/`，衣橱资产位于 `assets/resource/image/assets/`。源码导出的 Pipeline 不会写入随发布包分发的 `assets/resource/pipeline/`。

安装版首次启动时会检查安装目录中的旧版 `jobs/` 和 `assets/resource/image/jobs/`。迁移采用“不覆盖已有文件”的方式，全部完成后才写入 `.layout-v1.json` 标记；中途失败可在下次启动重试。内置 Maa 资源保持只读，用户模板通过可写 `resource/` 目录作为覆盖层加载。

`NNMAA_DATA_DIR` 可显式指定独立数据根目录，主要用于隔离测试或受管环境；它优先于默认路径和 `portable.flag`。指定后使用安装版子目录结构。不要把该变量指向不受信任的链接目录。

## MAA 兼容性

`assets/interface.json` 遵循 MaaFramework ProjectInterface v2，`assets/resource/pipeline/` 使用当前 Pipeline Schema。兼容的 MAA 通用 UI 可通过“游戏包名”覆盖启动节点；默认包名为 `com.papegames.nn4`，不同渠道请按实际包名修改。

修改 ProjectInterface 或 Pipeline 后运行：

```powershell
python tools/validate_schema.py
```

## 打包发布包

下面只讲 Windows 本地打包；macOS 构建由 GitHub Actions 负责生成 ZIP。

### Windows v2.1.0

在 Windows 项目根目录执行：

```powershell
python -m pip install -r tools/requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_release.ps1 -Version v2.1.0
```

Windows 构建还需要 Inno Setup 6。打包脚本会先校验 ProjectInterface 和 Pipeline Schema，再运行单元测试，使用 PyInstaller 构建一次洁净应用，然后分别生成便携 ZIP 和安装程序。归档和安装程序都生成完毕后，脚本才恢复本地 `dist/NnMaa/` 的旧用例和引用模板：

```text
release/NnMaa-v2.1.0-win-x64.zip
release/NnMaa-v2.1.0-setup.exe
```

普通用户优先运行 `NnMaa-v2.1.0-setup.exe`；安装器创建开始菜单快捷方式，并可选择创建桌面快捷方式。程序升级或卸载后，`%LOCALAPPDATA%\NnMaa` 中的用例和模板继续保留。

需要免安装时，解压完整 ZIP 后运行 `NnMaa/NnMaa.exe`。不要只复制 EXE；`_internal/`、`assets/`、`jobs/`、`platform-tools/` 和 `portable.flag` 共同构成便携版。当前安装程序未做代码签名，Windows SmartScreen 可能在首次运行时提示确认。
