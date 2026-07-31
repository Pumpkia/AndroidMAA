# QQ 自动登录 - MaaQQLogin

基于 [MaaFramework](https://github.com/MaaXYZ/MaaFramework) 的 QQ 桌面端自动登录工具。

## 环境要求

- Windows 10/11
- Python 3.10+
- 已安装 QQ（桌面版）

## 快速开始

### 第一步：准备模板图片

1. 打开 QQ 登录窗口
2. 运行 ImageCropper 工具连接 QQ 窗口进行截图：
   ```bash
   cd ImageCropper
   python main.py
   # 选择 Win32 → 找到 "QQ" 窗口
   ```
3. 框选并保存以下关键区域（按 S 保存）：

| 模板图片 | 说明 |
|---------|------|
| `账号输入框.png` | QQ号输入框区域 |
| `密码输入框.png` | 密码输入框区域 |
| `登录按钮.png` | "登录"按钮 |
| `账号密码登录.png` | 从二维码切换到账号密码的入口（新版QQ需要） |
| `登录成功标志.png` | 登录成功后的某个固定元素（如主面板图标） |

4. 将截图放入 `assets/resource/image/` 目录

### 第二步：修改配置

编辑 `assets/resource/pipeline/login.json`：
- 修改 `输入账号` 节点中的 QQ 号
- 修改 `输入密码` 节点中的密码
- 修改 `打开QQ` 节点中 QQ 的安装路径

编辑 `assets/interface.json`：
- 根据你的 QQ 版本调整 `class_regex` 和 `window_regex`
- 如果截图黑屏，尝试切换 `screencap` 方式

### 第三步：运行

```bash
# 使用 MaaFramework CLI 运行
MaaPiCli --interface=assets/interface.json

# 或使用 Python 脚本
pip install MaaFw
python -c "
import maa
from maa.toolkit import Toolkit
from maa.resource import Resource
from maa.controller import Win32Controller

Toolkit.init()
resource = Resource()
resource.load('assets')
controller = Win32Controller()
controller.connect()
tasker = maa.Tasker()
tasker.bind(resource, controller)
tasker.post_task('QQLogin')
tasker.wait()
"
```

## 项目结构

```
MaaQQLogin/
├── assets/
│   ├── interface.json        # 项目配置（控制器、任务定义）
│   └── resource/
│       ├── image/            # 模板匹配用的截图
│       │   ├── 账号输入框.png
│       │   ├── 密码输入框.png
│       │   ├── 登录按钮.png
│       │   └── ...
│       └── pipeline/
│           └── login.json    # 登录流程定义
├── tools/
│   └── install.py            # 打包脚本
└── README.md
```

## 注意事项

- **不要用于他人账号**，仅用于学习 MaaFramework 的自动化技术
- QQ 版本更新后界面可能变化，需要重新截图
- 如果遇到验证码，Pipeline 会自动停止，需要手动处理
- Win32 截图方式推荐优先尝试 `PrintWindow`，失败再换 `DXGI_DesktopDup`
## QQ App 作业工作台

`QQJobEditor.exe` 是一个单程序工作台，包含“用例录制”和“作业执行”两个界面。两个界面在同一进程内切换，并共享程序目录下唯一的 `jobs/` 作业库与 `assets/resource/image/jobs/` 模板库。

```bash
job-editor.bat
# 或
python tools/job_editor.py
```

用例录制：

1. 选择 ADB 设备并点击“截图”。编辑器会按 MaaFramework 的坐标规则把截图短边归一化为 720。
2. 选择“框选识别模板”，在 QQ 截图上框出按钮或图标，填写步骤名称后新增步骤。
3. 使用“输入文本”快速添加 `InputText` 步骤；使用“等待延迟”添加纯等待步骤。
4. 每个步骤都可以分别设置执行前延迟和执行后延迟，并可在设备上单步预览。
5. 在“作业库”中填写分类，作业会按分类树展示。选中其他用例后可将其设为当前作业的前置用例，并调整执行顺序。
6. 第一次点击“保存”会直接写入 `jobs/<分类>/<作业名>.maa_job.json`，继续编辑后再次点击“保存”会更新同一文件；只有“另存为”才会询问新路径。
7. 保存作业后可以导出 Pipeline，也可以切换到“作业执行”界面直接运行。前置用例会递归拼接到当前作业之前，循环依赖会被拦截。

作业执行：

1. 从按分类展示的作业库中搜索并将作业加入执行队列。
2. 调整队列顺序，选择 ADB 设备后点击“开始执行”。
3. 界面会实时显示 MaaFramework 的识别、动作及任务结果；运行中可以停止。
4. 点击“返回用例录制”可回到编辑界面，作业路径和模板路径不会改变。

模板保存在 `assets/resource/image/jobs/`，作业保存在 `jobs/<分类>/`，Pipeline 保存在 `assets/resource/pipeline/`。

支持的识别类型为 `TemplateMatch`、`OCR`、`DirectHit`；支持的动作类型为 `Click`、`Swipe`、`InputText`、`ClickKey`、`DoNothing`。导出的入口节点名会在完成提示中显示，可加入 `assets/interface.json` 的任务列表后由 Maa 通用 UI 执行。

## 打包 Windows 程序

在项目根目录运行：

~~~powershell
python -m pip install -r tools/requirements.txt
powershell -ExecutionPolicy Bypass -File tools/build_release.ps1 -Version v1.0.0
~~~

脚本会先运行单元测试，然后生成 `release/QQJobEditor-v1.0.0-win-x64.zip`。解压后运行 `QQJobEditor/QQJobEditor.exe`；`assets/`、`jobs/` 和 `platform-tools/` 必须与程序一起保留。
