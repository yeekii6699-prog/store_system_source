from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Tuple

from loguru import logger

try:
    import pythoncom
except ImportError:  # pragma: no cover
    pythoncom = None

from src.services.feishu import FeishuClient
from src.services.wechat import WeChatRPA


def _normalize_welcome_step(data: Dict[str, Any]) -> Dict[str, str] | None:
    action = str((data or {}).get("type") or "").strip().lower()
    if action == "text":
        content = str(data.get("content") or "").strip()
        if content:
            return {"type": "text", "content": content}
    elif action == "image":
        path = str(data.get("path") or "").strip()
        if path:
            return {"type": "image", "path": path}
    elif action == "link":
        url = str(data.get("url") or "").strip()
        if url:
            step = {"type": "link", "url": url}
            title = str(data.get("title") or "").strip()
            if title:
                step["title"] = title
            return step
    return None


def _load_welcome_steps(cfg: Dict[str, str]) -> List[Dict[str, str]]:
    steps: List[Dict[str, str]] = []
    raw = (cfg.get("WELCOME_STEPS") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        normalized = _normalize_welcome_step(item)
                        if normalized:
                            steps.append(normalized)
        except json.JSONDecodeError as exc:
            logger.warning("欢迎步骤配置解析失败，将回落至旧版字段: {}", exc)

    if not steps:
        legacy_text = (cfg.get("WELCOME_TEXT") or "").strip()
        if legacy_text:
            steps.append({"type": "text", "content": legacy_text})
        legacy_images = [
            part.strip()
            for part in (cfg.get("WELCOME_IMAGE_PATHS") or "").split("|")
            if part.strip()
        ]
        for image in legacy_images:
            steps.append({"type": "image", "path": image})
    return steps


def _extract_phone_and_name(fields: Dict[str, Any]) -> Tuple[str, str]:
    raw_phone = fields.get("手机号")
    phone = ""
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
    return phone, name.strip()


class TaskEngine:
    """Background worker that polls Feishu tasks and drives the WeChat RPA."""

    def __init__(self, cfg: Dict[str, str]) -> None:
        self.cfg = cfg
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="task-engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        co_initialized = False
        if pythoncom is not None:
            try:
                pythoncom.CoInitialize()
                co_initialized = True
            except Exception:
                logger.warning("COM 初始化失败，可能影响 RPA：{}", "CoInitialize 调用异常")

        try:
            feishu = FeishuClient(
                app_id=self.cfg.get("FEISHU_APP_ID"),
                app_secret=self.cfg.get("FEISHU_APP_SECRET"),
                task_table_url=self.cfg.get("FEISHU_TABLE_URL"),
                profile_table_url=self.cfg.get("FEISHU_PROFILE_TABLE_URL"),
            )
            wechat = WeChatRPA(exec_path=self.cfg.get("WECHAT_EXEC_PATH", ""))

            welcome_enabled = (self.cfg.get("WELCOME_ENABLED") or "0") == "1"
            welcome_steps = _load_welcome_steps(self.cfg)
            if welcome_enabled and not welcome_steps:
                logger.warning("已启用首次欢迎包，但没有配置任何步骤，将跳过自动发送。")
                welcome_enabled = False

            logger.info("系统启动，进入双队列任务循环...")
            while not self.stop_event.is_set():
                self._handle_apply_queue(feishu, wechat)
                self._handle_welcome_queue(feishu, wechat, welcome_enabled, welcome_steps)
                self.stop_event.wait(5)
        except Exception as exc:  # noqa: BLE001
            if not self.stop_event.is_set():
                logger.exception("任务引擎发生未处理异常: {}", exc)
        finally:
            if co_initialized and pythoncom is not None:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _handle_apply_queue(self, feishu: FeishuClient, wechat: WeChatRPA) -> None:
        tasks = feishu.fetch_tasks_by_status(["待添加"])
        if not tasks:
            return
        for item in tasks:
            record_id = item.get("record_id") or item.get("recordId")
            fields = item.get("fields", {})
            phone, _ = _extract_phone_and_name(fields)
            if not phone:
                logger.warning("记录缺少手机号，跳过 [{}]", record_id)
                continue

            relationship = wechat.check_relationship(phone)
            logger.info("[申请队列] 手机:{}, 关系检测: {}", phone, relationship)
            if relationship == "friend":
                logger.info("{} 已经是好友，进入发送队列", phone)
                feishu.update_status(record_id, "已申请")
                continue
            if relationship == "stranger":
                if wechat.apply_friend(phone):
                    feishu.update_status(record_id, "已申请")
                else:
                    logger.warning("申请发送失败 [{}]", phone)
                continue
            if relationship == "not_found":
                logger.warning("未在微信中找到 [{}]，标记为“未找到”", phone)
                feishu.update_status(record_id, "未找到")
                continue
            logger.warning("无法确定 [{}] 关系状态，稍后重试", phone)

    def _handle_welcome_queue(
        self,
        feishu: FeishuClient,
        wechat: WeChatRPA,
        welcome_enabled: bool,
        welcome_steps: List[Dict[str, str]],
    ) -> None:
        tasks = feishu.fetch_tasks_by_status(["已申请"])
        if not tasks:
            return
        for item in tasks:
            record_id = item.get("record_id") or item.get("recordId")
            fields = item.get("fields", {})
            phone, name = _extract_phone_and_name(fields)
            if not phone:
                logger.warning("记录缺少手机号，跳过 [{}]", record_id)
                continue

            relationship = wechat.check_relationship(phone)
            logger.info("[欢迎队列] 手机:{}, 关系检测: {}", phone, relationship)
            if relationship == "not_found":
                logger.warning("[欢迎队列] {} 在微信中未找到记录，保持“已申请”待人工确认", phone)
                continue
            if relationship != "friend":
                logger.debug("{} 尚未通过验证，等待下一轮", phone)
                continue

            send_ok = True
            if welcome_enabled and welcome_steps:
                search_keys = [phone]
                if name:
                    search_keys.append(name)
                    search_keys.append(f"{phone}-{name}")
                try:
                    send_ok = wechat.send_welcome_package(search_keys, welcome_steps)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("发送欢迎包异常 [{}]: {}", phone, exc)
                    send_ok = False

            if send_ok:
                feishu.update_status(record_id, "已绑定")
            else:
                logger.warning("{} 欢迎消息发送失败，保持“已申请”供人工处理", phone)
