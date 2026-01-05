from __future__ import annotations

import json
import random
import requests
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
from src.config.network import network_config


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
        self._passive_thread: threading.Thread | None = None
        self.wechat_lock = threading.Lock()
        self.feishu: FeishuClient | None = None
        self.wechat: WeChatRPA | None = None
        self.welcome_enabled: bool = False
        self.welcome_steps: List[Dict[str, str]] = []
        self.passive_scan_interval: float = float(self.cfg.get("MONITOR_SCAN_INTERVAL") or 30)  # 使用配置文件中的扫描间隔
        self.passive_scan_jitter: float = float(self.cfg.get("PASSIVE_SCAN_JITTER") or 10)  # 减少抖动时间

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.stop_event.clear()

        # 显示网络环境信息
        network_info = network_config.get_network_info()
        if network_info.get("has_vpn"):
            logger.info("🌐 检测到VPN/代理环境: {}", network_info)
        elif network_info.get("system_proxy"):
            logger.info("🔌 检测到系统代理: {}", network_info["system_proxy"])

        # 测试网络连接
        logger.info("🔍 测试飞书服务器连接...")
        if not network_config.test_connection():
            logger.warning("⚠️ 网络连接测试失败，但继续尝试初始化")
            logger.warning("   如果持续失败，请检查：")
            logger.warning("   1. VPN/代理设置是否正确")
            logger.warning("   2. 网络连接是否正常")
            logger.warning("   3. 在配置中设置 NETWORK_PROXY 或禁用 SSL 验证")

        # 增强飞书客户端初始化的错误处理
        try:
            self.feishu = FeishuClient(
                app_id=self.cfg.get("FEISHU_APP_ID"),
                app_secret=self.cfg.get("FEISHU_APP_SECRET"),
                task_table_url=self.cfg.get("FEISHU_TABLE_URL"),
                profile_table_url=self.cfg.get("FEISHU_PROFILE_TABLE_URL"),
            )
            logger.info("飞书客户端初始化成功")
        except requests.exceptions.SSLError as ssl_err:
            logger.error("❌ 飞书客户端初始化失败 - SSL连接错误: {}", ssl_err)
            logger.error("   建议检查：")
            logger.error("   1. 网络连接是否正常")
            logger.error("   2. 防火墙或代理设置")
            logger.error("   3. 系统时间是否正确")
            raise RuntimeError("飞书服务连接失败，请检查网络环境后重试")
        except requests.exceptions.ConnectionError as conn_err:
            logger.error("❌ 飞书客户端初始化失败 - 网络连接错误: {}", conn_err)
            raise RuntimeError("无法连接到飞书服务器，请检查网络连接")
        except Exception as e:
            logger.error("❌ 飞书客户端初始化失败: {}", e)
            logger.error("   请检查配置文件中的飞书应用凭据是否正确")
            raise
        self.wechat = WeChatRPA(exec_path=self.cfg.get("WECHAT_EXEC_PATH", ""))
        self.welcome_enabled = (self.cfg.get("WELCOME_ENABLED") or "0") == "1"
        self.welcome_steps = _load_welcome_steps(self.cfg)
        if self.welcome_enabled and not self.welcome_steps:
            logger.warning("已启用首次欢迎包，但没有配置任何步骤，将跳过自动发送")
            self.welcome_enabled = False

        self._thread = threading.Thread(target=self._run, name="task-engine", daemon=True)
        self._thread.start()
        self._passive_thread = threading.Thread(target=self._run_passive_monitor, name="passive-monitor", daemon=True)
        self._passive_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self._passive_thread and self._passive_thread.is_alive():
            self._passive_thread.join(timeout=2)

    def _run(self) -> None:
        co_initialized = False
        if pythoncom is not None:
            try:
                pythoncom.CoInitialize()
                co_initialized = True
            except Exception:
                logger.warning("COM 初始化失败，可能影响 RPA：{}", "CoInitialize 调用异常")

        try:
            feishu = self.feishu
            wechat = self.wechat
            welcome_enabled = self.welcome_enabled
            welcome_steps = self.welcome_steps
            if feishu is None or wechat is None:
                logger.error("未初始化飞书/微信客户端，系统不能启动")
                return

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

    def _run_passive_monitor(self) -> None:
        co_initialized = False
        if pythoncom is not None:
            try:
                pythoncom.CoInitialize()
                co_initialized = True
            except Exception:
                logger.warning("COM 初始化失败，可能影响被动监听：{}", "CoInitialize 调用异常")

        try:
            scan_count = 0
            while not self.stop_event.is_set():
                scan_count += 1
                logger.debug("🔍 开始第 {} 次被动扫描 (间隔: {:.1f}s)", scan_count, self.passive_scan_interval)
                self._handle_passive_new_friends()

                wait_seconds = self.passive_scan_interval + random.uniform(-self.passive_scan_jitter, self.passive_scan_jitter)
                wait_seconds = max(10.0, wait_seconds)  # 最少10秒间隔
                logger.debug("⏰ 被动监听等待 {:.1f} 秒后进行下次扫描", wait_seconds)
                self.stop_event.wait(wait_seconds)
        except Exception as exc:  # noqa: BLE001
            if not self.stop_event.is_set():
                logger.exception("被动监听线程异常 {}", exc)
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

            with self.wechat_lock:
                relationship = wechat.check_relationship(phone)
            logger.info("[申请队列] 手机:{}, 关系检测: {}", phone, relationship)
            if relationship == "friend":
                logger.info("{} 已经是好友，进入发送队列", phone)
                feishu.update_status(record_id, "已申请")
                continue
            if relationship == "stranger":
                with self.wechat_lock:
                    apply_ok = wechat.apply_friend(phone)
                if apply_ok:
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
        # 查询"已申请"（旧流程）和"未发送"（被动扫描新流程）的任务
        tasks = feishu.fetch_tasks_by_status(["已申请", "未发送"])
        if not tasks:
            return
        for item in tasks:
            record_id = item.get("record_id") or item.get("recordId")
            fields = item.get("fields", {})
            phone, name = _extract_phone_and_name(fields)
            if not phone:
                logger.warning("记录缺少手机号，跳过 [{}]", record_id)
                continue

            with self.wechat_lock:
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
                    with self.wechat_lock:
                        send_ok = wechat.send_welcome_package(search_keys, welcome_steps)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("发送欢迎包异常 [{}]: {}", phone, exc)
                    send_ok = False

            if send_ok:
                feishu.update_status(record_id, "已绑定")
            else:
                logger.warning("{} 欢迎消息发送失败，保持“已申请”供人工处理", phone)

    def _handle_passive_new_friends(self) -> None:
        feishu = self.feishu
        wechat = self.wechat
        if feishu is None or wechat is None:
            return

        with self.wechat_lock:
            contacts = wechat.scan_passive_new_friends()
            logger.debug("被动扫描完成，发现 {} 个新好友", len(contacts))

        if not contacts:
            return

        for contact in contacts:
            phone = (contact.get("wechat_id") or "").strip()
            nickname = (contact.get("nickname") or "").strip()
            remark = (contact.get("remark") or "").strip()
            if not phone:
                logger.debug("被动监听到的好友缺少微信号，跳过: {}", contact)
                continue

            try:
                # 被动扫描发现的好友，写入飞书时状态为"未发送"
                feishu.upsert_contact_profile(phone=phone, name=nickname, remark=remark, status="未发送")
                logger.info("[被动同步] {} -> 已写入飞书，状态: 未发送", phone)
            except requests.HTTPError as http_err:
                logger.error("飞书API网络错误 [{}]: {} - 检查网络连接和API配置", phone, http_err)
                # 网络错误暂时跳过，下次轮询可能恢复
                continue
            except RuntimeError as api_err:
                logger.error("飞书API业务错误 [{}]: {} - 检查数据格式和权限", phone, api_err)
                # API错误可能是数据问题，继续处理下一个
                continue
            except ValueError as data_err:
                logger.warning("数据验证失败 [{}]: {} - 微信号可能无效", phone, data_err)
                # 数据错误跳过该联系人
                continue
            except Exception as exc:  # noqa: BLE001
                logger.error("未知错误 [{}]: {} - 建议检查系统状态", phone, exc)
                # 未知错误记录但继续处理
                continue
