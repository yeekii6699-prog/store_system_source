"""
统一的日志配置，包含本地文件、控制台与飞书 webhook 告警。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from loguru import logger

from .settings import get_config


def _get_webhook_url() -> str:
    cfg = get_config()
    return (
        cfg.get("FEISHU_WEBHOOK_URL") or os.getenv("FEISHU_WEBHOOK_URL", "")
    ).strip()


def _get_alert_cooldown() -> int:
    cfg = get_config()
    raw = cfg.get("ALERT_COOLDOWN") or os.getenv("ALERT_COOLDOWN", "60")
    try:
        return int(float(raw))
    except ValueError:
        return 60


def _get_log_retention_days() -> int:
    cfg = get_config()
    raw = cfg.get("LOG_RETENTION_DAYS") or os.getenv("LOG_RETENTION_DAYS", "7")
    try:
        return int(float(raw))
    except ValueError:
        return 7


def _get_log_level() -> str:
    cfg = get_config()
    return (cfg.get("LOG_LEVEL") or os.getenv("LOG_LEVEL", "INFO")).strip() or "INFO"


_last_push_ts: float = 0.0
_last_screenshot_ts: float = 0.0
_image_token: Optional[str] = None
_image_token_expire_at: float = 0.0


def _notify_startup() -> None:
    """隐藏推送启动信息给飞书，防止控制台噪音。"""
    webhook_url = _get_webhook_url()
    if not webhook_url or webhook_url == "YOUR_WEBHOOK_URL_HERE":
        return
    payload = {
        "msg_type": "text",
        "content": {"text": "WeChat RPA 进程已启动，继续为宝守护业务 ❤️"},
    }
    try:
        requests.post(webhook_url, json=payload, timeout=5)
    except Exception:
        pass


def feishu_sink(message) -> None:  # type: ignore[override]
    """将 ERROR/CRITICAL 日志推送到飞书群，包含冷却机制。"""
    global _last_push_ts
    record = message.record
    level_name = record["level"].name
    if level_name not in {"ERROR", "CRITICAL"}:
        return

    now = time.time()
    cooldown = _get_alert_cooldown()
    if now - _last_push_ts < cooldown:
        return

    file_name = getattr(record.get("file"), "name", record.get("file", ""))
    line_no = record.get("line", "")
    timestamp = record["time"].strftime("%Y-%m-%d %H:%M:%S")
    detail = record.get("message", "")
    text = f"报错：{timestamp}\n文件: {file_name}:{line_no}\n详情: {detail}"
    payload = {"msg_type": "text", "content": {"text": text}}

    webhook_url = _get_webhook_url()
    try:
        if webhook_url and webhook_url != "YOUR_WEBHOOK_URL_HERE":
            requests.post(webhook_url, json=payload, timeout=5)
        _last_push_ts = now
    except Exception:
        # 避免日志发送失败导致死循环，这里静默吞掉。
        pass


def _get_tenant_access_token() -> Optional[str]:
    global _image_token, _image_token_expire_at
    now = time.time()
    if _image_token and now < _image_token_expire_at - 60:
        return _image_token

    cfg = get_config()
    app_id = (cfg.get("FEISHU_APP_ID") or "").strip()
    app_secret = (cfg.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        return None

    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    payload = {"app_id": app_id, "app_secret": app_secret}
    try:
        resp = requests.post(url, json=payload, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            return None
    except Exception:
        return None

    _image_token = data.get("tenant_access_token")
    expire = int(data.get("expire", 0))
    _image_token_expire_at = now + expire
    return _image_token


def _upload_feishu_image(image_path: Path) -> Optional[str]:
    if not image_path.exists():
        return None

    token = _get_tenant_access_token()
    if not token:
        return None

    url = "https://open.feishu.cn/open-apis/im/v1/images"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with image_path.open("rb") as f:
            files = {"image": (image_path.name, f, "image/png")}
            data = {"image_type": "message"}
            resp = requests.post(
                url, headers=headers, files=files, data=data, timeout=10
            )
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("code") != 0:
                return None
            return payload.get("data", {}).get("image_key")
    except Exception:
        return None


def push_feishu_screenshot(reason: str, image_path: Path) -> None:
    global _last_screenshot_ts
    webhook_url = _get_webhook_url()
    if not webhook_url or webhook_url == "YOUR_WEBHOOK_URL_HERE":
        return

    now = time.time()
    cooldown = _get_alert_cooldown()
    if now - _last_screenshot_ts < cooldown:
        return

    text = f"微信未检测到，已截图\n原因: {reason}"
    try:
        requests.post(
            webhook_url,
            json={"msg_type": "text", "content": {"text": text}},
            timeout=5,
        )
    except Exception:
        pass

    _last_screenshot_ts = now

    image_key = _upload_feishu_image(image_path)
    if not image_key:
        return

    try:
        requests.post(
            webhook_url,
            json={"msg_type": "image", "content": {"image_key": image_key}},
            timeout=5,
        )
    except Exception:
        pass


def setup_logger() -> None:
    """初始化 loguru，输出到控制台、本地文件与飞书。"""
    logs_dir = Path(__file__).resolve().parents[2] / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger.remove()
    log_level = _get_log_level()
    retention_days = _get_log_retention_days()
    if sys.stderr:
        logger.add(
            sys.stderr,
            level=log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}",
        )
    logger.add(
        logs_dir / "shop_os_{time}.log",
        rotation="00:00",
        retention=f"{retention_days} days",
        encoding="utf-8",
        level=log_level,
    )
    logger.add(feishu_sink, level="ERROR")
    _notify_startup()
