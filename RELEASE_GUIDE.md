# 发布与热更新操作手册

适用于当前的 `launcher.py` + `main_bot.exe` 热更新机制，含打包、发布、更新、回滚步骤。

## 一、环境准备
- Python 3.10（与生产一致），已安装依赖：`pip install -r requirements.txt`
- PyInstaller：`pip install pyinstaller`
- 确保无正在运行的 `main_bot.exe`（任务管理器结束，避免占用导致覆盖失败）。
- 代码版本：包含最新版的 `launcher.py`、`src/main.py`、`config.py` 等。

## 二、本地打包流程
1) 退出正在运行的 `main_bot.exe`，删除或备份 `dist/main_bot.exe`（防止占用）。
2) 进入项目根目录：`cd F:\code\store_system_source`
3) 执行打包（无窗口模式）：  
   ```bash
   pyinstaller -F -w src/main.py -n main_bot --clean --noconfirm
   ```
4) 产物检查：`dist/main_bot.exe` 生成成功，无报错。

## 三、制作发布压缩包
1) 进入 `dist` 目录，确认 `main_bot.exe` 体积和时间戳正确。
2) 打 zip 包（zip 内仅包含 `main_bot.exe`）：  
   - GUI：右键压缩为 `main_bot.zip`  
   - 或命令行：`powershell Compress-Archive -Path main_bot.exe -DestinationPath main_bot.zip -Force`
3) 得到 `main_bot.zip`，用于发布。

## 四、发布端文件与格式
1) 上传 `main_bot.zip` 至发布地址（推荐 Gitee Releases 附件），获取 **直链 URL**。  
2) 编辑远程 `version.txt`，格式必须为：  
   ```
   <版本号>|<zip下载直链>
   ```
   示例：  
   ```
   1.2.3|https://gitee.com/yeekii77/store_system/releases/download/1.2.3/main_bot.zip
   ```
   - 有 `|`：launcher 将使用提供的下载链接。  
   - 无 `|`：launcher 将回退到代码内默认 `ZIP_URL`，可能下载旧包，不建议。  
3) 确保 `version.txt` 与 `main_bot.zip` 都可公开访问，`VERSION_URL` 指向的就是该 `version.txt`。

## 五、客户端更新流程（用户侧）
1) 用户运行 `launcher.py` 或其打包版（启动器）。  
2) 启动器行为：  
   - 读取远程 `version.txt`，解析 `版本|URL`。  
   - 读取本地 `local_version.txt`（无则用 `CURRENT_VERSION`）。  
   - 仅当远程版本大于本地版本时，使用解析出的 URL 下载 `main_bot.zip`。  
   - 解压出 `main_bot.exe`，覆盖本地旧版，写入新版本号到 `local_version.txt`。  
3) 若 `version.txt` 缺少 URL 或格式错误，会提示“远程版本文件格式错误，未找到下载链接”，需修正远程文件。

## 六、回滚流程
1) 重新上传一个旧版本的 `main_bot.zip` 至发布地址，获取旧包直链。  
2) 修改远程 `version.txt` 为旧版本号和旧包直链：`旧版本号|旧包URL`。  
3) 用户下次启动 launcher 时会检测到“远程版本 > 本地版本”不成立（若旧版本号小于本地，需要先下调本地 `local_version.txt` 或使用更高版本号的回滚包）。

## 七、常见问题与排查
- **打包时 PermissionError 拒绝访问 dist/main_bot.exe**：进程仍在占用。结束任务管理器中的 `main_bot.exe`，或重命名输出。  
- **更新后仍是旧版本**：检查 `version.txt` 是否带正确直链，确认 `local_version.txt` 是否被更新；必要时删除本地 `local_version.txt` 强制全新对比。  
- **下载 403/被拦截**：已在 launcher 中设置浏览器 UA，确保链接可匿名访问且允许重定向。  
- **解压失败/未找到 main_bot.exe**：确认 zip 内部确实包含 `main_bot.exe`，且不在多层子目录。  
- **进程无法退出**：新版 main.py 已使用守护线程并在关闭时 `os._exit(0)`，若仍残留，手动结束进程后重新运行。

## 八、每次发布前的检查清单
- [ ] 代码已合入最新 launcher 和业务逻辑。  
- [ ] 本地打包成功，`dist/main_bot.exe` 运行正常。  
- [ ] `main_bot.zip` 内仅包含新版 exe。  
- [ ] `version.txt` 已更新为 `新版本号|新直链`。  
- [ ] 远程直链可下载，`version.txt` 可访问。  
- [ ] 通知用户退出旧进程再运行 launcher 以触发更新。
