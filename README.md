# Store Digital Operation System (Feishu + WeChat RPA)

面向门店/客服的自动加好友与回写流程：从飞书多维表格（任务表）拉取手机号，校验客户表状态后，调用 PC 微信 RPA 添加好友，并回写处理状态。支持 Wiki 链接自动转 Base Token、GUI 配置与日志查看。

## 关键指标对齐表

| 指标 | 项目侧价值/目标 | 系统抓手 |
| --- | --- | --- |
| 电话→加微→到店转化率 | 《项目商业与运营概览》在“数据统计与看板”中要求重点跟踪电话→加微→到店漏斗，并以此衡量门店增长质量。 | README 描述系统会从飞书任务表拉取手机号、核对客户表，再调用 PC 微信 RPA 自动加友并回写处理状态，天然沉淀漏斗数据。 |
| 加友处理 SLA | 项目概览的“微信加好友与备注”明确前台录号后需即时自动加友，保障“手机号-姓名”链路不卡顿。 | 系统支持轮询任务表+PC 微信 RPA，启动 GUI 即可实时查看任务状态，避免人工延迟。 |
| 预约冲突率 / 到店提醒及时率 | 项目概览的“自动接待与提醒”提到要自动防撞单、并在到店前 1 小时提醒前台和技师。 | README 的配置项要求填写预约表/客户表链接，系统据此在后台线程轮询，结合日志监控来保障预约执行。 |
| 数据沉淀与交接完整度 | 项目概览强调客户档案、预约流水、交接都在飞书，保证“数据归属老板”。 | README 里的配置方式和日志章节说明所有运行参数、客户/预约表链接与日志都在本地受控，方便审计与交接。 |
| 人效节省（小时/日） | “预期收益”估算每日可节省 1-2 小时重复操作，是 ROI 的硬指标。 | README 的功能特性（自动轮询、PC RPA、GUI 可视化）展示了具体的自动化手段，可被量化成节省的人力工时。 |

## 功能特性
- 自动获取飞书 `tenant_access_token`，轮询任务表，按状态更新处理结果。
- 支持飞书 Wiki 链接：自动将 `/wiki/<token>?table=tblxxx` 转换为 Bitable Base Token，再继续 API 调用。
- PC 微信 RPA：搜索手机号、发送好友申请，支持自定义验证语；好友通过请直接在工作微信开启“自动通过好友验证”，系统不再额外模拟点击，避免多余操作。
- 首次欢迎包：勾选 GUI 中的欢迎配置后，可上传多张门店指引图片与多行文案，系统在首次加好友成功后立即推送，减少人工复制粘贴。
- GUI 主控台：启动即显示窗口，后台线程跑业务，可实时查看日志，手动停止立即退出。
- 飞书远程告警：loguru ERROR/CRITICAL 日志会通过 webhook 推送到指定群聊（带 60s 冷却），方便远程调度排障。
- 热更新启动器：读取远程 `version.txt` 的 `版本|zip直链`，下载解压 `main_bot.exe` 替换本地。

## 目录结构（组件化）
```
.
|-- README.md
|-- RELEASE_GUIDE.md
|-- requirements.txt
|-- config.ini                 # 运行后生成/保存用户配置
|-- launcher.py                # 热更新启动器
|-- src
|   |-- main.py                # 简化入口：logger -> 自检 -> ConsoleApp
|   |-- config/
|   |   |-- settings.py        # GUI 配置与持久化（原 config.py）
|   |   `-- logger.py          # 日志 & 飞书 webhook sink
|   |-- core/
|   |   |-- system.py          # DPI、自检、环境检测
|   |   `-- engine.py          # TaskEngine（飞书轮询 + 微信 RPA）
|   |-- services/
|   |   |-- feishu.py          # 飞书客户端封装
|   |   `-- wechat.py          # 微信 RPA 实现
|   |-- ui/
|   |   `-- console.py         # Tk 控制台（日志/按钮/状态）
|   `-- utils/
|       `-- table_inspector.py # 飞书表结构辅助脚本
`-- .env.example
```

## 环境要求
- Windows，Python 3.10+（开发/调试）；打包使用 PyInstaller。
- 已安装 PC 微信客户端，可被 RPA 控件访问。
- 可访问飞书开放平台接口，并已在应用中开通 Wiki/Bitable 相关权限。

## 安装依赖
```bash
pip install -r requirements.txt
```

## 配置方式
### 1) GUI 配置（推荐）
- 运行 `python -m src.main` 或打包后的 exe，启动后会弹出配置窗口（即使已有 config.ini 也会显示）。
- 字段：
  - 飞书 App ID / App Secret
  - 预约表链接 (任务表)   -> `FEISHU_TABLE_URL`
  - 客户表链接 (资料表)   -> `FEISHU_PROFILE_TABLE_URL`
  - PC微信启动路径        -> `WECHAT_EXEC_PATH`
- 勾选“记住配置”可写入 `config.ini`；未勾选则仅本次生效。

### 2) 环境变量或 config.ini
- 可提前在环境变量中设置上述键，或手动编写 `config.ini` 的 `[DEFAULT]`。
- 支持 `SKIP_CONFIG_UI=1` 跳过 GUI，前提是必填项已具备。

### 3) Wiki 链接支持
- 粘贴形如 `https://ai.feishu.cn/wiki/<wiki_token>?table=tblxxx` 的链接即可。
- 代码会先调用 `wiki/v2/spaces/get_node` 将 Wiki Token 转换为 Base Token，再拼出标准 Bitable 记录接口 URL。

### 4) 首次欢迎包配置（可选）
- 在 GUI 界面下方的“首次欢迎包配置”区域勾选“启用加好友成功后自动发送门店指引”即可生效。
- “欢迎文案”支持多行输入，程序会自动用 `Shift+Enter` 插入换行，最后一次性发送。
- “图片附件”允许一次选择多张 PNG/JPG/JPEG/BMP/GIF，RPA 会依次触发 `Ctrl+O`、填入路径并发送。
- 如果希望通过环境变量或 `config.ini` 直接配置，可使用：
  - `WELCOME_ENABLED=1`：代表开启欢迎包；
  - `WELCOME_TEXT=第一行\n第二行`：多行之间用换行符；
  - `WELCOME_IMAGE_PATHS=D:\guide\a.png|D:\guide\b.jpg`：使用 `|` 连接多张图片的绝对路径。
- 仅当 RPA 返回状态为 `added`（首次加友）时推送，若发送失败会在日志提醒人工补发。

## 运行方式
### 源码运行
```bash
python -m src.main
```
- 启动窗口：“Store 小助手 - 运行中”
- 窗口包含：状态标签、日志区域、停止按钮；业务轮询在后台守护线程执行。
- 关闭窗口/点击停止，会发送停止信号并调用 `os._exit(0)` 强制退出，避免残留进程。

### 查看飞书字段样例
```bash
python -m src.utils.table_inspector
```

## 日志
- 文件：`logs/run.log`（自动轮转，UTF-8）
- 窗口日志：通过队列实时显示。

## 热更新/启动器（launcher.py）
- 远程 `version.txt` 格式：`版本号|zip直链`（例如 `1.2.3|https://.../main_bot.zip`）
- 若缺少 `|url`，将回退到代码内默认 `ZIP_URL`（可能是旧包）。
- 更新流程：比对远程版本 > 本地 `local_version.txt` -> 按链接下载 zip -> 解压出 `main_bot.exe` 覆盖 -> 写入新版本号。
- 详情参见 `RELEASE_GUIDE.md`。

## 常见问题
- **打包时报 PermissionError 无法覆盖 dist/main_bot.exe**：旧进程仍在运行或被杀毒占用，先结束进程/放行后再打包，或更换输出名。
- **更新后仍是旧版本**：检查远程 `version.txt` 是否正确写了直链；必要时删除本地 `local_version.txt` 后再运行 launcher。
- **无法退出/残留进程**：新版 main.py 已在关闭时 `stop_event.set()` 后 `os._exit(0)`，若仍残留，手动结束进程。
- **下载 403/重定向**：launcher 已伪装浏览器 UA 并启用 allow_redirects；确认下载直链可匿名访问。

## 发布检查清单（简版）
- [ ] `dist/main_bot.exe` 打包并跑通
- [ ] `main_bot.zip` 内仅包含最新 exe
- [ ] 远程 `version.txt` 已更新为 `新版本|新直链`
- [ ] 远程直链可下载，version.txt 可访问
- [ ] 通知用户退出旧进程并运行 launcher 触发更新

更多发布与回滚细节见 `RELEASE_GUIDE.md`。***
