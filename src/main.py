"""
业务主入口：轮询飞书任务，调用微信 RPA 添加好友，并回写处理状态。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests
from loguru import logger

from config import WECHAT_EXEC_PATH
from src.feishu_client import FeishuClient
from src.wechat_bot import WeChatRPA

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 配置日志输出，保留文件并输出到控制台
logger.remove()
logger.add(LOG_DIR / "run.log", rotation="20 MB", retention="7 days", encoding="utf-8")
logger.add(sys.stdout, colorize=False, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")


def main() -> None:
    """
    业务循环：
    1. 从飞书任务表获取待处理手机号
    2. 查询客户表判断是否已绑定
    3. 已绑定客户跳过，新客户触发微信加好友
    4. 回写飞书处理状态
    """
    feishu = FeishuClient()
    wechat = WeChatRPA(exec_path=WECHAT_EXEC_PATH)
    
    # 本地缓存，防止单次循环内重复处理同一个ID（可选）
    processed_cache = set()

    logger.info("系统启动，开始轮询飞书任务...")

    while True:
        try:
            tasks = feishu.fetch_new_tasks()
            if not tasks:
                # 没任务时稍微降低频率，避免刷屏
                time.sleep(5)
                continue

            for item in tasks:
                record_id = item.get("record_id") or item.get("recordId")
                
                # 简单去重保护
                if record_id in processed_cache:
                    continue

                fields = item.get("fields", {})
                raw_phone = fields.get("手机号")  # 客户表手机号字段
                status = fields.get("微信绑定状态", "")

                # ================= 核心修复部分开始 =================
                phone: str = ""
                if isinstance(raw_phone, str):
                    phone = raw_phone.strip()
                elif isinstance(raw_phone, (int, float)):
                    phone = str(int(raw_phone)) # 去掉小数点
                elif isinstance(raw_phone, list) and raw_phone:
                    first_item = raw_phone[0]
                    # 判断列表里是否为字典（飞书标准格式）
                    if isinstance(first_item, dict):
                        # 依次尝试获取：电话字段(full_number)、文本字段(text)、公式字段(value)
                        phone = first_item.get("full_number") or first_item.get("text") or first_item.get("value") or ""
                    else:
                        phone = str(first_item)
                
                phone = phone.strip() # 再次去空格
                # ================= 核心修复部分结束 =================

                if not phone:
                    logger.warning("任务缺少手机号字段或格式异常，跳过: {}", item)
                    if record_id:
                        feishu.mark_processed(record_id)
                        processed_cache.add(record_id)
                    continue

                # 解析姓名 (兼容富文本结构)
                name_value = fields.get("姓名", "")
                name = ""
                if isinstance(name_value, list) and name_value:
                    first = name_value[0]
                    if isinstance(first, dict):
                        name = first.get("text", "")
                    else:
                        name = str(first)
                elif isinstance(name_value, str):
                    name = name_value
                
                logger.info("处理任务 -> 手机:[{}] 姓名:[{}] 当前状态:[{}]", phone, name, status)

                # --- 业务逻辑判断 ---
                
                # 1. 已经是好友/已添加 -> 跳过
                if status == "已添加":
                    logger.info("状态已是[已添加]，跳过: {}", phone)
                    if record_id:
                        feishu.mark_processed(record_id)
                        processed_cache.add(record_id)
                    continue

                # 2. 已经绑定系统 -> 跳过
                if status == "已绑定":
                    logger.info("状态已是[已绑定]，无需添加: {}", phone)
                    if record_id:
                        feishu.mark_processed(record_id)
                        processed_cache.add(record_id)
                    continue

                # 3. 执行添加好友
                verify_msg = f"您好 {name}，这里是 Store 数字运营系统，请通过好友以便后续沟通。"
                result = wechat.add_friend(phone, verify_msg=verify_msg)
                logger.info("RPA执行结果 [{}]: {}", phone, result)

                # 4. 根据结果回写状态
                # 如果是 "added"(已申请) 或 "exists"(已经是好友)，都算处理成功
                if record_id:
                    try:
                        if result in ("added", "exists"):
                            # mark_processed 会把微信绑定状态写为“已添加”
                            feishu.mark_processed(record_id)
                            processed_cache.add(record_id)
                        elif result == "failed":
                            logger.error("RPA操作失败，将飞书状态改为[添加失败]")
                            feishu.mark_failed(record_id)
                            processed_cache.add(record_id)
                    except requests.HTTPError as mark_err:
                        logger.error("回写飞书失败 (HTTP): {}", mark_err)
                    except Exception as mark_err:  # noqa: BLE001
                        logger.error("回写飞书失败 (未知): {}", mark_err)

            time.sleep(2) # 每一个批次处理完休息一下
            
        except KeyboardInterrupt:
            logger.info("程序被手动终止")
            break
        except Exception as exc:  # noqa: BLE001
            logger.exception("主循环发生未知异常: {}", exc)
            time.sleep(5)

if __name__ == "__main__":
    main()
