# Store Digital Operation System (Feishu + WeChat RPA)

面向门店/客服的自动加好友与回写流程：从飞书多维表格（任务表）拉取手机号，校验客户表状态后，调用 PC 微信 RPA 添加好友，并回写处理状态。支持 Wiki 链接自动转 Base Token、GUI 配置与日志查看。

## 功能特性
- 自动获取飞书 `tenant_access_token`，轮询任务表，按状态更新处理结果。
- 支持飞书 Wiki 链接：自动将 `/wiki/<token>?table=tblxxx` 转换为 Bitable Base Token，再继续 API 调用。
- PC 微信 RPA：搜索手机号、发送好友申请，支持自定义验证语。
- GUI 主控台：启动即显示窗口，后台线程跑业务，可实时查看日志，手动停止立即退出。
- 热更新启动器：读取远程 `version.txt` 的 `版本|zip直链`，下载解压 `main_bot.exe` 替换本地。

## 目录结构
```
.
|-- README.md
|-- RELEASE_GUIDE.md          # 发布与热更新操作手册
|-- requirements.txt
|-- config.ini                # 运行时生成的配置文件
|-- config.py                 # 配置加载与 Tk 界面
|-- launcher.py               # 热更新启动器
|-- src
|   |-- main.py               # GUI + 后台业务线程
|   |-- feishu_client.py      # 飞书 API/Wiki 转 Base 封装
|   |-- wechat_bot.py         # 微信 RPA
|   |-- inspect_tables.py     # 打印表结构样例
|   `-- debug_feishu.py
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
python -m src.inspect_tables
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
