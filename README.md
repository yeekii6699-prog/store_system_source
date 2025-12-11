# Store Digital Operation System (Feishu + WeChat RPA)

面向店铺数字运营的自动化机器人：从飞书多维表格拉取待处理手机号，校验客户信息后通过微信桌面端自动加好友，并回写处理状态。

## 功能概览
- 自动获取飞书 `tenant_access_token`，按状态筛选任务、更新处理状态。
- 查询客户资料表，判断手机号是否已绑定。
- 通过微信桌面端 RPA 搜索手机号并发送好友申请，支持发送验证信息。
- 日志记录至 `logs/run.log`，便于追踪。

## 目录结构
```
store_system/
  .env.example        # 环境变量模板，复制为 .env 并填充
  .gitignore          # 已忽略 .env、logs/、__pycache__/
  requirements.txt    # 依赖列表
  config.py           # 环境变量加载与配置
  src/
    feishu_client.py  # 飞书 API 封装
    wechat_bot.py     # 微信 RPA 封装
    main.py           # 主业务循环入口
    inspect_tables.py # 辅助脚本，查看飞书表字段与样例
```

## 环境要求
- Python 3.10+ 建议
- 已安装微信桌面客户端，并可通过 RPA 控件访问
- 可访问飞书开放平台接口

## 配置步骤
1. 复制环境模板并填写真实值（不要提交 `.env` 到版本库）:
   ```bash
   cd store_system
   cp .env.example .env
   ```
2. 编辑 `.env`，填入飞书应用与表格信息、微信可执行路径：
   ```env
   FEISHU_APP_ID=your_app_id
   FEISHU_APP_SECRET=your_app_secret
   FEISHU_TABLE_URL=https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
   FEISHU_PROFILE_TABLE_URL=https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
   WECHAT_EXEC_PATH=C:\\Program Files\\Tencent\\WeChat\\WeChat.exe
   ```
   > 提示：`FEISHU_TABLE_URL` 为任务表，需包含字段 `Processing Status`（值: Pending/Processed）与手机号字段；`FEISHU_PROFILE_TABLE_URL` 为客户表，需包含 `手机号`/`Phone` 与状态字段（示例: `🟢已绑定`）。

3. 安装依赖:
   ```bash
   pip install -r requirements.txt
   ```

## 运行
在项目根目录执行：
```bash
python -m src.main
```

### 查看飞书表字段与样例
如需确认字段名或状态值（表情字段也支持），可运行辅助脚本：
```bash
python -m src.inspect_tables
```
它会打印任务表和客户表的字段列表及部分样例数据，方便在代码里对应字段名，无需手动翻找。

## 日志
- 默认输出到终端，并写入 `logs/run.log`（轮转保留，UTF-8 编码）。

## 安全与版本控制
- `.env` 仅存放本地/部署环境变量，已被 `.gitignore` 忽略，切勿提交。
- 代码与配置完全分离，便于在不同环境下复用。
