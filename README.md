# MaaQQLogin

MaaQQLogin 是基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 的 Android ADB 自动化作业工作台，面向 QQ App 等移动端场景。它在一个窗口中完成设备截图、步骤录制、作业管理和队列回放。

## 环境要求

- Windows 10/11（64 位）
- Python 3.10 或更高版本
- 已安装 QQ App 的 Android 真机或模拟器
- 设备已开启开发者选项和 USB 调试，并完成 ADB 授权

项目自带 Windows `platform-tools`。也可以使用系统 `PATH` 中的 `adb`。

## 界面布局

- 顶部通过“步骤录制”和“步骤回放”在同一窗口内切换工作区。
- 左侧始终显示设备预览，可选择 ADB 设备、刷新设备列表并截图。录制模式还提供框选模板、点击位置和滑动轨迹工具。
- 右侧“步骤录制”工作区用于编排步骤、设置识别与动作参数、管理作业库以及保存或导出作业。
- 右侧“步骤回放”工作区用于搜索作业、编辑执行队列、开始或停止任务，并查看实时执行日志。

录制和回放共享当前设备、`jobs/` 作业库及 `assets/resource/image/jobs/` 模板库，切换工作区不会打开第二个主窗口。

## 源码运行

在项目根目录执行：

```powershell
python -m pip install -r tools/requirements.txt
python tools/job_editor.py
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

### 录制作业

1. 在顶部选择“步骤录制”，新建作业或从“作业库”载入已有作业。
2. 获取设备截图后，在左侧选择“框选模板”“点击位置”或“滑动轨迹”，并在预览中完成标记。
3. 在右侧填写步骤名称，选择识别类型和动作类型，按需设置 OCR 文字、输入内容、阈值与延迟。
4. 将步骤加入列表，调整顺序，并使用“在设备上预览此动作”检查单步效果。
5. 点击“保存”。作业写入 `jobs/<分类>/`，模板写入 `assets/resource/image/jobs/<作业名>/`。
6. 需要 Maa Pipeline 文件时，点击“导出”。

支持的识别类型包括 `TemplateMatch`、`OCR` 和 `DirectHit`；支持的动作类型包括 `Click`、`Swipe`、`InputText`、`ClickKey` 和 `DoNothing`。

### 回放作业

1. 在顶部选择“步骤回放”。
2. 从作业库选择任务并加入执行队列。
3. 使用“上移”“下移”“移除”调整队列。
4. 确认设备后点击“开始执行”，在执行日志中查看识别、动作和任务结果。
5. 运行期间可点击“停止”；完成后可直接切回“步骤录制”继续修改。

## 打包 Windows v1.1.1

在项目根目录执行：

```powershell
python -m pip install -r tools/requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_release.ps1 -Version v1.1.1
```

打包脚本会先运行单元测试，再使用 PyInstaller 生成：

```text
release/QQJobEditor-v1.1.1-win-x64.zip
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
|-- jobs/                             # 作业 JSON 与分类目录
|-- platform-tools/                   # Windows ADB 运行时
|-- tools/
|   |-- job_editor.py                 # 主窗口与步骤录制
|   |-- job_runner_app.py             # 同窗步骤回放工作区
|   |-- job_runner.py                 # MaaFramework 执行器
|   |-- job_model.py                  # 作业模型与 Pipeline 导出
|   |-- build_release.ps1             # Windows 打包脚本
|   `-- requirements.txt              # Python 依赖
|-- QQJobEditor.spec                  # PyInstaller 配置
|-- job-editor.bat                    # 源码启动入口
`-- README.md
```

## 注意事项

- 截图和坐标按 MaaFramework 的短边 720 规则归一化；设备分辨率或 QQ 界面变化后应重新检查模板。
- `InputText` 内容会明文保存在作业 JSON 中，不要写入密码、Token 等敏感信息。
- 仅对自己拥有或获授权的设备和账号执行自动化任务。
