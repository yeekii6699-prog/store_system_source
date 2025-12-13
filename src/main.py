"""
业务主入口：轮询飞书任务，调用微信 RPA 添加好友，并回写处理状态。
启动时始终显示 Tk 窗口，并在后台线程跑任务。
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import time
from pathlib import Path
from tkinter import Tk, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import requests
from loguru import logger

from config import get_config
from src.feishu_client import FeishuClient
from src.wechat_bot import WeChatRPA

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_QUEUE: "queue.Queue[str]" = queue.Queue(maxsize=500)

# ============== 日志配置 ==============
logger.remove()
logger.add(LOG_DIR / "run.log", rotation="20 MB", retention="7 days", encoding="utf-8")
if sys.stderr is not None:
    logger.add(sys.stderr, colorize=False, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")


def _queue_sink(message) -> None:  # type: ignore[override]
    """将日志推送到 GUI 队列用于实时展示。"""
    try:
        LOG_QUEUE.put_nowait(str(message).rstrip("\n"))
    except Exception:
        pass


# 将 GUI sink 放在最后，避免阻塞主日志输出
logger.add(_queue_sink, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")


def run_bot(stop_event: threading.Event, cfg: dict[str, str]) -> None:
    """
    业务循环：
    1. 从飞书任务表获取待处理手机号
    2. 查询客户表判断是否已绑定
    3. 已绑定客户跳过，新客户触发微信加好友
    4. 回写飞书处理状态
    """
    feishu = FeishuClient(
        app_id=cfg.get("FEISHU_APP_ID"),
        app_secret=cfg.get("FEISHU_APP_SECRET"),
        task_table_url=cfg.get("FEISHU_TABLE_URL"),
        profile_table_url=cfg.get("FEISHU_PROFILE_TABLE_URL"),
    )
    wechat = WeChatRPA(exec_path=cfg.get("WECHAT_EXEC_PATH", ""))
    processed_cache = set()
    welcome_enabled = (cfg.get("WELCOME_ENABLED") or "0") == "1"
    welcome_text = (cfg.get("WELCOME_TEXT") or "").strip()
    welcome_images = [item.strip() for item in (cfg.get("WELCOME_IMAGE_PATHS") or "").split("|") if item.strip()]
    if welcome_enabled and not (welcome_text or welcome_images):
        logger.warning("已启用首次欢迎包，但没有配置文案或图片，将跳过自动发送以免空消息。")
        welcome_enabled = False
    welcome_cache: set[str] = set()

    logger.info("系统启动，开始轮询飞书任务...")

    while not stop_event.is_set():
        try:
            tasks = feishu.fetch_new_tasks()
            if not tasks:
                time.sleep(5)
                continue

            for item in tasks:
                if stop_event.is_set():
                    break

                record_id = item.get("record_id") or item.get("recordId")

                if record_id in processed_cache:
                    continue

                fields = item.get("fields", {})
                raw_phone = fields.get("手机号")
                status = fields.get("微信绑定状态", "")

                phone: str = ""
                if isinstance(raw_phone, str):
                    phone = raw_phone.strip()
                elif isinstance(raw_phone, (int, float)):
                    phone = str(int(raw_phone))
                elif isinstance(raw_phone, list) and raw_phone:
                    first_item = raw_phone[0]
                    if isinstance(first_item, dict):
                        phone = first_item.get("full_number") or first_item.get("text") or first_item.get("value") or ""
                    else:
                        phone = str(first_item)

                phone = phone.strip()

                if not phone:
                    logger.warning("任务缺少手机号字段或格式异常，跳过: {}", item)
                    if record_id:
                        feishu.mark_processed(record_id)
                        processed_cache.add(record_id)
                    continue

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

                if status == "已添加":
                    logger.info("状态已是[已添加]，跳过: {}", phone)
                    if record_id:
                        feishu.mark_processed(record_id)
                        processed_cache.add(record_id)
                    continue

                if status == "已绑定":
                    logger.info("状态已是[已绑定]，无需添加: {}", phone)
                    if record_id:
                        feishu.mark_processed(record_id)
                        processed_cache.add(record_id)
                    continue

                verify_msg = f"您好 {name}，这里是 Store 数字运营系统，请通过好友以便后续沟通。"
                result = wechat.add_friend(phone, verify_msg=verify_msg)
                logger.info("RPA执行结果 [{}]: {}", phone, result)

                should_send_welcome = (
                    welcome_enabled
                    and result == "added"
                    and phone not in welcome_cache
                )
                if should_send_welcome:
                    welcome_cache.add(phone)
                    search_keys = [phone]
                    if name:
                        search_keys.append(name)
                        search_keys.append(f"{phone}-{name}")
                    try:
                        sent = wechat.send_welcome_package(search_keys, welcome_text, welcome_images)
                        if sent:
                            logger.info("已自动发送门店指引给 [{}]", phone)
                        else:
                            # Plan B: 若无法自动发送，提醒前台人工补发，避免客户冷场。
                            logger.warning("自动欢迎包未成功发送 [{}]，请人工确认。", phone)
                    except Exception as welcome_err:  # noqa: BLE001
                        logger.warning("发送欢迎包异常 [{}]: {}", phone, welcome_err)

                if record_id:
                    try:
                        if result in ("added", "exists"):
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

            time.sleep(2)

        except Exception as exc:  # noqa: BLE001
            if stop_event.is_set():
                break
            logger.exception("主循环发生未知异常: {}", exc)
            time.sleep(5)

    logger.info("停止信号已收到，退出任务轮询。")


def _start_gui() -> None:
    """启动 Tk 窗口与后台线程。"""
    try:
        cfg = get_config()
    except Exception as exc:  # noqa: BLE001
        logger.error("配置加载失败：{}", exc)
        try:
            root = Tk()
            root.withdraw()
            messagebox.showerror("配置未完成", f"请填写配置后重试：{exc}", parent=root)
            root.destroy()
        except Exception:
            pass
        return
    stop_event = threading.Event()
    root = Tk()
    root.title("Store 小助手 - 运行中")
    root.geometry("760x520")
    root.resizable(False, False)

    main_frame = ttk.Frame(root, padding=12)
    main_frame.pack(fill="both", expand=True)

    status_label = ttk.Label(main_frame, text="正在监控飞书任务...", font=("Segoe UI", 12, "bold"))
    status_label.pack(anchor="w", pady=(0, 8))

    log_box = ScrolledText(main_frame, height=24, width=90, state="disabled", wrap="word")
    log_box.pack(fill="both", expand=True, pady=(0, 8))

    btn_frame = ttk.Frame(main_frame)
    btn_frame.pack(fill="x")
    stop_btn = ttk.Button(btn_frame, text="停止程序", width=20)
    stop_btn.pack(side="right")

    def poll_log_queue() -> None:
        try:
            while True:
                line = LOG_QUEUE.get_nowait()
                log_box.configure(state="normal")
                log_box.insert("end", line + "\n")
                log_box.see("end")
                log_box.configure(state="disabled")
        except queue.Empty:
            pass
        root.after(500, poll_log_queue)

    def stop_runner() -> None:
        stop_btn.config(state="disabled", text="正在停止...")
        status_label.config(text="正在停止，请稍候...")
        stop_event.set()
        # 守护线程 + 强制退出，避免第三方库挂起进程
        try:
            root.destroy()
        except Exception:
            pass
        os._exit(0)

    def on_close() -> None:
        stop_runner()

    stop_btn.config(command=stop_runner)
    root.protocol("WM_DELETE_WINDOW", on_close)

    worker = threading.Thread(target=run_bot, args=(stop_event, cfg), daemon=True)
    worker.start()

    poll_log_queue()
    root.mainloop()


if __name__ == "__main__":
    _start_gui()
