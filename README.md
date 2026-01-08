# Store Digital Operation System

门店自动化运营系统：从飞书拉取任务，自动通过 PC 微信添加好友，并回写处理状态。

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)](https://github.com/yeekii6699-prog/store_system_source)

## 功能特性

| 功能 | 说明 |
|-----|------|
| 飞书自动轮询 | 获取 tenant_access_token，轮询任务表并更新状态 |
| Wiki 链接转换 | 自动将 `/wiki/<token>` 转换为 Bitable Base Token |
| 微信主动添加 | 搜索手机号、发送好友申请，支持自定义验证语 |
| 首次欢迎包 | 加好友成功后自动推送门店指引图片+文案 |
| 新的好友监控 | 自动扫描「通讯录 → 新的好友 → 等待验证」，获取微信号写入飞书 |
| GUI 控制台 | 实时日志查看、手动停止、状态监控、监控频率调节 |
| 远程告警 | ERROR/CRITICAL 日志通过飞书 webhook 推送 |
| 热更新启动器 | 自动下载更新包，无需手动替换 |

## 目录结构

```
.
|-- README.md
|-- RELEASE_GUIDE.md
|-- requirements.txt
|-- config.ini                 # 运行后生成的用户配置
|-- launcher.py                # 热更新启动器
|-- .env.example               # 环境变量示例
|-- src/
|   |-- main.py                # 入口：logger -> 自检 -> ConsoleApp
|   |-- config/
|   |   |-- settings.py        # GUI 配置与持久化
|   |   |-- logger.py          # 日志 & 飞书 webhook
|   |   |-- network.py         # 网络配置与 SSL
|   |-- core/
|   |   |-- system.py          # DPI、自检、环境检测
|   |   |-- engine.py          # TaskEngine（飞书轮询 + 微信 RPA）
|   |-- services/
|   |   |-- feishu.py          # 飞书客户端
|   |   |-- wechat.py          # 微信 RPA（包含通讯录扫描）
|   |-- ui/
|   |   |-- console.py         # Tk 控制台
|   `-- utils/
|       |-- table_inspector.py # 飞书表结构辅助脚本
|-- ui_probe.py                # UI 控件调试工具
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置方式

#### GUI 配置（推荐）

运行 `python -m src.main` 或打包后的 exe，弹出配置窗口：

| 字段 | 环境变量 | 说明 |
|-----|---------|------|
| 飞书 App ID | `FEISHU_APP_ID` | 应用唯一标识 |
| 飞书 App Secret | `FEISHU_APP_SECRET` | 应用密钥 |
| 任务表链接 | `FEISHU_TABLE_URL` | 待处理任务来源 |
| 客户表链接 | `FEISHU_PROFILE_TABLE_URL` | 客户档案存储 |
| 微信启动路径 | `WECHAT_EXEC_PATH` | 微信可执行文件位置 |
| 启用欢迎包 | `WELCOME_ENABLED` | 0=关闭，1=开启 |

#### 环境变量或 config.ini

提前设置环境变量，或手动编写 `config.ini` 的 `[DEFAULT]` 段。

#### Wiki 链接支持

粘贴 `https://ai.feishu.cn/wiki/<wiki_token>?table=tblxxx` 格式链接，系统自动转换。

### 3. 首次欢迎包（可选）

GUI 勾选启用后，可配置：

- **欢迎文案**：多行输入，程序自动处理换行
- **图片附件**：支持 PNG/JPG/JPG/GIF，多张依次发送

或通过环境变量配置：
```ini
WELCOME_ENABLED=1
WELCOME_TEXT=第一行\n第二行
WELCOME_IMAGE_PATHS=D:\guide\a.png|D:\guide\b.jpg
```

### 4. 新的好友监控

程序会自动监控微信「通讯录 → 新的好友 → 等待验证」列表：

- **监控频率**：默认 30 秒，可在 GUI 运行时实时调节（5-300秒）
- **操作流程**：点击待验证项 → 点击前往验证 → 点击确定 → 获取微信号 → 写入飞书状态「未发送」
- **自动去重**：好友通过后自动从列表移除，无需额外处理

### 5. 运行程序

```bash
python -m src.main
```

启动后窗口显示 "Store 小助手 - 运行中"，包含状态标签、监控频率调节、日志区域和停止按钮。

### 查看飞书字段样例

```bash
python -m src.utils.table_inspector
```

### UI 控件调试

如需调试微信 UI 控件定位，运行：

```bash
python ui_probe.py
```

将鼠标移动到目标位置，3秒后输出控件信息。

## 日志

- **文件**：`logs/run.log`（自动轮转，UTF-8 编码）
- **窗口**：通过队列实时显示

## 热更新启动器

`launcher.py` 读取远程 `version.txt` 格式：`版本号|zip直链`

```
更新流程：比对远程版本 → 下载 zip → 解压覆盖 → 写入版本号
```

## 常见问题

| 问题 | 解决方案 |
|-----|---------|
| 打包时 PermissionError | 结束旧进程或关闭杀毒软件 |
| 更新后仍是旧版本 | 删除 `local_version.txt` 后重试 |
| 无法退出/残留进程 | 手动结束进程或升级到新版 |
| 下载 403/重定向 | 确认下载链接可匿名访问 |
| 新的好友监控无响应 | 检查微信窗口可见性，查看 DEBUG 日志 |
| 微信 RPA 操作失败 | 确认 UI 自动化权限，尝试配置 WECHAT_EXEC_PATH |

## 发布检查清单

- [ ] `dist/main_bot.exe` 打包并测试通过
- [ ] `main_bot.zip` 内仅包含最新 exe
- [ ] 远程 `version.txt` 更新为 `新版本|新直链`
- [ ] 远程直链可正常下载
- [ ] 通知用户运行 launcher 触发更新

详细发布与回滚指南见 [RELEASE_GUIDE.md](./RELEASE_GUIDE.md)。
