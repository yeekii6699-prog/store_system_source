"""
统一的日志配置，包含本地文件、控制台与飞书 webhook 告警。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests
from loguru import logger

FEISHU_WEBHOOK_URL = "https://open.feishu.cn/open-apis/bot/v2/hook/f36edae0-95a4-4a59-b4da-ce58cff8f639"
COOLDOWN = 60  # 秒

_last_push_ts: float = 0.0


def feishu_sink(message) -> None:  # type: ignore[override]
    """将 ERROR/CRITICAL 日志推送到飞书群，包含冷却机制。"""
    global _last_push_ts
    record = message.record
    level_name = record["level"].name
    if level_name not in {"ERROR", "CRITICAL","WARNING"}:
        return

    now = time.time()
    if now - _last_push_ts < COOLDOWN:
        return

    file_name = getattr(record.get("file"), "name", record.get("file", ""))
    line_no = record.get("line", "")
    timestamp = record["time"].strftime("%Y-%m-%d %H:%M:%S")
    detail = record.get("message", "")
    text = (
        f"报错：{timestamp}\n"
        f"文件: {file_name}:{line_no}\n"
        f"详情: {detail}"
    )
    payload = {"msg_type": "text", "content": {"text": text}}

    try:
        if FEISHU_WEBHOOK_URL and FEISHU_WEBHOOK_URL != "YOUR_WEBHOOK_URL_HERE":
            requests.post(FEISHU_WEBHOOK_URL, json=payload, timeout=5)
        _last_push_ts = now
    except Exception:
        # 避免日志发送失败导致死循环，这里静默吞掉。
        pass


def setup_logger() -> None:
    """初始化 loguru，输出到控制台、本地文件与飞书。"""
    logs_dir = Path(__file__).resolve().parent.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")
    logger.add(
        logs_dir / "shop_os_{time}.log",
        rotation="00:00",
        retention="7 days",
        encoding="utf-8",
        level="DEBUG",
    )
    logger.add(feishu_sink, level="WARNING")

