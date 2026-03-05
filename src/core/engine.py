from __future__ import annotations

import json
import random
import requests
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, cast

from loguru import logger

try:
    import pythoncom
except ImportError:  # pragma: no cover
    pythoncom = None

from src.services.feishu import FeishuClient
from src.services.followup import (
    LLMClient,
    build_snapshot_hash,
    evaluate_candidate,
    format_time,
    load_followup_runtime_config,
    make_followup_candidate,
)
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


def _load_welcome_steps(cfg: Dict[str, str]) -> List[Any]:
    steps: List[Any] = []
    raw = (cfg.get("WELCOME_STEPS") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        normalized = _normalize_welcome_step(item)
                        if normalized:
                            steps.append(cast(Dict[str, str | None], normalized))
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
            phone = (
                first_item.get("full_number")
                or first_item.get("text")
                or first_item.get("value")
                or ""
            )
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
        self.pause_event = threading.Event()  # 暂停控制事件
        self._thread: threading.Thread | None = None
        self._passive_thread: threading.Thread | None = None
        self.wechat_lock = threading.Lock()
        self.feishu: FeishuClient | None = None
        self.wechat: WeChatRPA | None = None
        self.welcome_enabled: bool = False
        self.welcome_steps: List[Any] = []
        self.passive_scan_interval: float = float(
            self.cfg.get("NEW_FRIEND_SCAN_INTERVAL") or 30
        )  # 新的好友扫描间隔
        self.passive_scan_jitter: float = float(
            self.cfg.get("PASSIVE_SCAN_JITTER") or 5
        )  # 减少抖动时间
        self.feishu_poll_interval: float = float(
            self.cfg.get("FEISHU_POLL_INTERVAL") or 5
        )  # 飞书轮询间隔，默认5秒
        # 统计计数器
        self.apply_count = 0  # 申请处理数
        self.welcome_count = 0  # 欢迎发送数
        self.fail_count = 0  # 失败数
        self.followup_generated_count = 0  # 回访文案生成数
        self.followup_sent_count = 0  # 回访发送数
        self.followup_skip_count = 0  # 回访跳过数
        self.followup_fail_count = 0  # 回访失败数
        self._co_initialized = False  # COM初始化状态
        self.followup_cfg = load_followup_runtime_config(self.cfg)
        self.llm_client = LLMClient(self.followup_cfg)
        self._last_followup_scan_ts: float = 0.0
        self._followup_request_lock = threading.Lock()
        self._followup_request_items: list[dict[str, str]] = []
        self._followup_prompt_overrides: dict[str, str] = {}
        self._followup_run_lock = threading.Lock()
        self._manual_followup_lock = threading.Lock()
        self._manual_followup_record_ids: set[str] = set()
        self._followup_auto_started = False
        self._followup_waiting_logged = False

        # 新增配置属性
        self.rpa_delay_min: float = float(self.cfg.get("RPA_DELAY_MIN") or 0.5)
        self.rpa_delay_max: float = float(self.cfg.get("RPA_DELAY_MAX") or 1.5)
        self.relationship_timeout: float = float(
            self.cfg.get("RELATIONSHIP_DETECT_TIMEOUT") or 6.0
        )
        self.profile_timeout: float = float(self.cfg.get("PROFILE_WAIT_TIMEOUT") or 4.0)
        self.button_timeout: float = float(self.cfg.get("BUTTON_FIND_TIMEOUT") or 3.0)
        self.feishu_rate_limit_cooldown: float = float(
            self.cfg.get("FEISHU_RATE_LIMIT_COOLDOWN") or 0.3
        )
        self.welcome_step_delay: float = float(
            self.cfg.get("WELCOME_STEP_DELAY") or 1.0
        )
        self.welcome_retry_count: int = int(self.cfg.get("WELCOME_RETRY_COUNT") or 0)
        self.log_retention_days: int = int(self.cfg.get("LOG_RETENTION_DAYS") or 7)
        self.log_level: str = self.cfg.get("LOG_LEVEL") or "INFO"
        self.alert_cooldown: int = int(self.cfg.get("ALERT_COOLDOWN") or 60)

    def set_monitor_interval(self, seconds: float) -> None:
        """设置被动监控扫描间隔（秒）"""
        self.passive_scan_interval = max(5.0, float(seconds))
        logger.info("监控频率已更新: {:.1f}秒", self.passive_scan_interval)

    def set_jitter(self, seconds: float) -> None:
        """设置扫描抖动时间（秒）"""
        self.passive_scan_jitter = max(0.0, float(seconds))
        logger.info("扫描抖动已更新: {:.1f}秒", self.passive_scan_jitter)

    def set_feishu_poll_interval(self, seconds: float) -> None:
        """设置飞书轮询间隔（秒）"""
        self.feishu_poll_interval = max(3.0, float(seconds))
        logger.info("飞书轮询频率已更新: {:.1f}秒", self.feishu_poll_interval)

    def toggle_welcome(self, enabled: bool) -> None:
        """切换欢迎包开关"""
        self.welcome_enabled = enabled
        logger.info("欢迎包功能已{}", "启用" if enabled else "禁用")

    def is_paused(self) -> bool:
        """检查是否已暂停"""
        return self.pause_event.is_set()

    def is_running(self) -> bool:
        """检查主任务线程是否处于运行态。"""
        return bool(
            self._thread and self._thread.is_alive() and not self.stop_event.is_set()
        )

    def pause(self) -> bool:
        """暂停监控，返回是否成功"""
        if self.is_paused():
            return False
        self.pause_event.set()
        logger.info("⏸️ 监控已暂停")
        # 释放COM资源
        self._release_com()
        return True

    def resume(self) -> bool:
        """继续监控，返回是否成功"""
        if not self.is_paused():
            return False
        self.pause_event.clear()
        logger.info("▶️ 监控已继续")
        return True

    def _release_com(self) -> None:
        """释放COM资源"""
        if self._co_initialized and pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
                self._co_initialized = False
                logger.debug("COM资源已释放")
            except Exception:
                pass

    def _reinit_com(self) -> None:
        """重新初始化COM资源"""
        if pythoncom is not None and not self._co_initialized:
            try:
                pythoncom.CoInitialize()
                self._co_initialized = True
                logger.debug("COM资源已重新初始化")
            except Exception:
                logger.warning("COM重新初始化失败")

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

        self._thread = threading.Thread(
            target=self._run, name="task-engine", daemon=True
        )
        self._thread.start()
        self._passive_thread = threading.Thread(
            target=self._run_passive_monitor, name="passive-monitor", daemon=True
        )
        self._passive_thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self._followup_auto_started = False
        self._followup_waiting_logged = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self._passive_thread and self._passive_thread.is_alive():
            self._passive_thread.join(timeout=2)

    def start_followup_auto(self) -> tuple[bool, str]:
        """手动开启自动回访循环。"""
        if not self.is_running():
            return False, "系统未运行，请先启动系统"

        self.followup_cfg = load_followup_runtime_config(self.cfg)
        if not self.followup_cfg.enabled:
            return False, "自动回访未启用，请先开启回访开关并保存配置"

        if self._followup_auto_started:
            return False, "自动回访已开始"

        self._followup_auto_started = True
        self._followup_waiting_logged = False
        logger.info("自动回访已手动启动")
        return True, "已开始自动回访"

    def _run(self) -> None:
        co_initialized = False
        if pythoncom is not None:
            try:
                pythoncom.CoInitialize()
                co_initialized = True
                self._co_initialized = True
            except Exception:
                logger.warning(
                    "COM 初始化失败，可能影响 RPA：{}", "CoInitialize 调用异常"
                )

        try:
            feishu = self.feishu
            wechat = self.wechat
            if feishu is None or wechat is None:
                logger.error("未初始化飞书/微信客户端，系统不能启动")
                return

            logger.info("系统启动，进入双队列任务循环...")
            self._followup_auto_started = False
            self._followup_waiting_logged = False
            while not self.stop_event.is_set():
                # 检查暂停状态
                while self.pause_event.is_set() and not self.stop_event.is_set():
                    self.stop_event.wait(0.2)
                if self.stop_event.is_set():
                    break

                self._handle_apply_queue(feishu, wechat)
                if self.stop_event.is_set():
                    break
                if self._followup_auto_started:
                    self._handle_followup_queue(feishu, wechat)
                elif self.followup_cfg.enabled and not self._followup_waiting_logged:
                    logger.info("自动回访待启动：请在回访页点击‘开始自动回访’")
                    self._followup_waiting_logged = True
                if self.stop_event.is_set():
                    break
                # 注意：不再调用 _handle_welcome_queue
                # 被动监控 (_handle_passive_new_friends) 会自动处理：
                #   - "已添加"的好友：匹配飞书记录 → 发送welcome → 更新为"已绑定"
                #   - "等待验证"的好友：自动前往验证 → 发送welcome → 写入飞书"已绑定"
                self.pause_event.wait(self.feishu_poll_interval)
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
                self._co_initialized = True
            except Exception:
                logger.warning(
                    "COM 初始化失败，可能影响被动监听：{}", "CoInitialize 调用异常"
                )

        try:
            scan_count = 0
            while not self.stop_event.is_set():
                # 检查暂停状态
                while self.pause_event.is_set() and not self.stop_event.is_set():
                    self.stop_event.wait(0.2)
                if self.stop_event.is_set():
                    break

                scan_count += 1
                logger.info(
                    "[被动扫描] 🔍 开始第 {} 次扫描 (间隔: {:.1f}s)",
                    scan_count,
                    self.passive_scan_interval,
                )
                self._handle_passive_new_friends()

                wait_seconds = self.passive_scan_interval + random.uniform(
                    -self.passive_scan_jitter, self.passive_scan_jitter
                )
                wait_seconds = max(10.0, wait_seconds)  # 最少10秒间隔
                logger.debug("⏰ 被动监听等待 {:.1f} 秒后进行下次扫描", wait_seconds)
                self.pause_event.wait(wait_seconds)
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
            if self._should_abort():
                return
            record_id = item.get("record_id") or item.get("recordId")
            if not record_id:
                logger.warning("记录缺少 record_id，跳过")
                continue
            record_id = str(record_id)
            fields = item.get("fields", {})
            phone, _ = _extract_phone_and_name(fields)
            if not phone:
                logger.warning("记录缺少手机号，跳过 [{}]", record_id)
                continue

            # 一次搜索完成所有操作：判断好友 + 获取昵称 + 发送申请
            with self.wechat_lock:
                if self._should_abort():
                    return
                profile_win = wechat._search_and_open_profile(phone)

            if self._should_abort():
                return
            if not profile_win:
                if wechat._has_add_friend_not_found_popup():
                    logger.warning(
                        "未找到 [{}] 的资料卡，确认弹窗提示，标记为未找到", phone
                    )
                    feishu.update_status(record_id, "未找到")
                    self.fail_count += 1
                else:
                    logger.warning(
                        "未找到 [{}] 的资料卡，但未出现提示，保留状态等待重试", phone
                    )
                continue

            try:
                # 判断好友关系
                if self._should_abort():
                    return
                relationship = wechat._detect_relationship_state(
                    [profile_win], timeout=self.relationship_timeout
                )
                logger.info("[申请队列] 手机:{}, 关系检测: {}", phone, relationship)

                if relationship == "friend":
                    # 已经是好友，直接发送welcome并更新为"已绑定"
                    logger.info("{} 已经是好友，直接发送welcome", phone)
                    with self.wechat_lock:
                        if self._should_abort():
                            return
                        enter_chat_ok = wechat._contacts._click_send_message_button()

                    if not enter_chat_ok:
                        logger.warning(
                            "[申请队列] 未找到'发消息'按钮，保持原状态等待重试 [{}]",
                            phone,
                        )
                        self.fail_count += 1
                        continue

                    self._send_welcome_and_update(
                        feishu,
                        wechat,
                        phone,
                        None,
                        record_id,
                        already_in_chat=True,
                    )
                    self.apply_count += 1
                    continue

                if relationship == "stranger":
                    # 获取昵称（从已打开的资料卡）
                    if self._should_abort():
                        return
                    nickname = wechat._extract_nickname_from_profile(profile_win)
                    logger.info("[申请队列] 获取到昵称: {}", nickname)

                    # 发送好友申请（资料卡已打开，直接点击添加）
                    with self.wechat_lock:
                        if self._should_abort():
                            return
                        try:
                            if profile_win.Exists(0):
                                profile_win.SetActive()
                                profile_win.SetFocus()
                        except Exception as exc:
                            logger.debug("[申请队列] 资料卡前置失败: {}", exc)
                        apply_ok = wechat._click_button(
                            "添加到通讯录",
                            timeout=wechat.button_timeout,
                            search_depth=10,
                            class_name="mmui::XOutlineButton",
                        )
                        if apply_ok:
                            time.sleep(1)
                            # 处理确认弹窗
                            confirm_windows = (
                                "申请添加朋友",
                                "发送好友申请",
                                "好友验证",
                                "通过朋友验证",
                            )
                            confirm_buttons = (
                                "确定",
                                "发送",
                                "Send",
                                "确定(&O)",
                                "确定(&S)",
                            )
                            wechat._handle_confirm_dialog(
                                confirm_windows, confirm_buttons, timeout=8.0
                            )

                    if apply_ok:
                        logger.info(
                            "[申请队列] {} 好友申请已发送，昵称: {}", phone, nickname
                        )
                        # 更新为"已申请"状态
                        feishu.update_status(record_id, "已申请")
                        # 将昵称写入飞书，方便后续被动监控通过昵称匹配
                        if nickname:
                            try:
                                feishu.update_record(record_id, {"昵称": nickname})
                                logger.info("[申请队列] 昵称已写入飞书: {}", nickname)
                            except Exception as e:
                                logger.warning("[申请队列] 写入昵称失败: {}", e)
                        self.apply_count += 1
                    else:
                        logger.warning("申请发送失败 [{}]", phone)
                        self.fail_count += 1
                    continue

                if relationship == "not_found":
                    if wechat._has_add_friend_not_found_popup():
                        logger.warning(
                            '未在微信中找到 [{}]，确认弹窗提示，标记为"未找到"', phone
                        )
                        feishu.update_status(record_id, "未找到")
                        self.fail_count += 1
                    else:
                        logger.warning(
                            "关系检测为未找到 [{}]，但未出现提示，保留状态等待重试",
                            phone,
                        )
                    continue

                logger.warning("无法确定 [{}] 关系状态，稍后重试", phone)
            finally:
                # 关闭资料卡窗口
                try:
                    if profile_win.Exists(0):
                        profile_win.SendKeys("{Esc}")
                except Exception:
                    pass

    def _send_welcome_and_update(
        self,
        feishu: FeishuClient,
        wechat: WeChatRPA,
        phone: str,
        name: str | None,
        record_id: str,
        already_in_chat: bool = False,
    ) -> None:
        """
        发送welcome并更新飞书状态。

        Args:
            feishu: 飞书客户端
            wechat: 微信RPA
            phone: 手机号/微信号
            name: 姓名（可选）
            record_id: 飞书记录ID
            already_in_chat: 是否已在聊天窗口中
        """
        if not self.welcome_enabled or not self.welcome_steps:
            # 没有启用welcome，直接更新状态
            feishu.update_status(record_id, "已绑定")
            return

        search_keys = [phone]
        if name:
            search_keys.append(name)
            search_keys.append(f"{phone}-{name}")

        try:
            with self.wechat_lock:
                send_ok = wechat.send_welcome_package(
                    search_keys,
                    self.welcome_steps,
                    already_in_chat=already_in_chat,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("发送欢迎包异常 [{}]: {}", phone, exc)
            send_ok = False

        if send_ok:
            feishu.update_status(record_id, "已绑定")
            self.welcome_count += 1
        else:
            logger.warning("[{}] welcome发送失败，保持原状态", phone)
            self.fail_count += 1

    def get_followup_request_items(self) -> list[dict[str, str]]:
        with self._followup_request_lock:
            return [dict(item) for item in self._followup_request_items]

    def get_followup_record_groups(self) -> dict[str, list[dict[str, Any]]]:
        client = self.feishu
        if client is None:
            client = FeishuClient(
                app_id=self.cfg.get("FEISHU_APP_ID"),
                app_secret=self.cfg.get("FEISHU_APP_SECRET"),
                task_table_url=self.cfg.get("FEISHU_TABLE_URL"),
                profile_table_url=self.cfg.get("FEISHU_PROFILE_TABLE_URL"),
            )
        return client.fetch_followup_record_groups(page_size=200)

    def run_manual_followup(self, record_ids: list[str]) -> dict[str, Any]:
        selected = {str(item or "").strip() for item in record_ids}
        selected.discard("")
        if not selected:
            return {
                "requested": 0,
                "matched": 0,
                "processed": 0,
                "message": "未选择回访用户",
            }

        local_co_initialized = False
        if pythoncom is not None:
            try:
                pythoncom.CoInitialize()
                local_co_initialized = True
            except Exception as exc:
                logger.warning("手动回访COM初始化失败: {}", exc)

        try:
            feishu = self.feishu
            if feishu is None:
                feishu = FeishuClient(
                    app_id=self.cfg.get("FEISHU_APP_ID"),
                    app_secret=self.cfg.get("FEISHU_APP_SECRET"),
                    task_table_url=self.cfg.get("FEISHU_TABLE_URL"),
                    profile_table_url=self.cfg.get("FEISHU_PROFILE_TABLE_URL"),
                )
                self.feishu = feishu

            wechat = self.wechat
            if wechat is None:
                wechat = WeChatRPA(exec_path=self.cfg.get("WECHAT_EXEC_PATH", ""))
                self.wechat = wechat

            with self._manual_followup_lock:
                self._manual_followup_record_ids = set(selected)

            matched, processed = self._handle_followup_queue(
                feishu,
                wechat,
                manual_record_ids=selected,
                force_run=True,
            )
            message = f"手动回访完成：匹配{matched}条，处理{processed}条"
            return {
                "requested": len(selected),
                "matched": matched,
                "processed": processed,
                "message": message,
            }
        finally:
            if local_co_initialized and pythoncom is not None:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def update_followup_request_prompt(self, record_id: str, prompt: str) -> bool:
        rid = str(record_id or "").strip()
        value = (prompt or "").strip()
        if not rid or not value:
            return False

        with self._followup_request_lock:
            updated = False
            for item in self._followup_request_items:
                if item.get("record_id") == rid:
                    item["prompt"] = value
                    item["updated_at"] = format_time(datetime.now())
                    updated = True
                    break
            if updated:
                self._followup_prompt_overrides[rid] = value
            return updated

    def _get_followup_prompt_override(self, record_id: str) -> str:
        with self._followup_request_lock:
            return self._followup_prompt_overrides.get(record_id, "")

    def _record_followup_request(
        self,
        record_id: str,
        customer: str,
        wechat_id: str,
        prompt: str,
        status: str,
    ) -> None:
        rid = str(record_id or "").strip()
        if not rid:
            return

        now_text = format_time(datetime.now())
        prompt_value = (prompt or "").strip()
        with self._followup_request_lock:
            target: dict[str, str] | None = None
            for item in self._followup_request_items:
                if item.get("record_id") == rid:
                    target = item
                    break

            if target is None:
                target = {
                    "record_id": rid,
                    "customer": customer,
                    "wechat_id": wechat_id,
                    "prompt": prompt_value,
                    "status": status,
                    "updated_at": now_text,
                }
                self._followup_request_items.insert(0, target)
                if len(self._followup_request_items) > 200:
                    self._followup_request_items = self._followup_request_items[:200]
            else:
                target["customer"] = customer
                target["wechat_id"] = wechat_id
                if prompt_value:
                    target["prompt"] = prompt_value
                target["status"] = status
                target["updated_at"] = now_text

    def _handle_followup_queue(
        self,
        feishu: FeishuClient,
        wechat: WeChatRPA,
        manual_record_ids: set[str] | None = None,
        force_run: bool = False,
    ) -> tuple[int, int]:
        self.followup_cfg = load_followup_runtime_config(self.cfg)
        self.llm_client = LLMClient(self.followup_cfg)
        if not self.followup_cfg.enabled and not force_run:
            return 0, 0

        selected_ids = set(manual_record_ids or set())
        if not selected_ids:
            with self._manual_followup_lock:
                if self._manual_followup_record_ids:
                    selected_ids = set(self._manual_followup_record_ids)
                    self._manual_followup_record_ids.clear()

        manual_mode = force_run or bool(selected_ids)

        acquired = self._followup_run_lock.acquire(blocking=False)
        if not acquired:
            if manual_mode:
                self._followup_run_lock.acquire()
                acquired = True
            else:
                logger.debug("回访处理仍在执行，跳过本轮自动回访")
                return 0, 0

        try:
            now_ts = time.time()
            if (
                not manual_mode
                and self.followup_cfg.enabled
                and self._last_followup_scan_ts > 0
                and now_ts - self._last_followup_scan_ts
                < self.followup_cfg.poll_interval
            ):
                return 0, 0

            try:
                items = feishu.fetch_followup_candidates(page_size=200)
                if not manual_mode:
                    self._last_followup_scan_ts = now_ts
            except Exception as exc:
                logger.warning("回访候选拉取失败: {}", exc)
                self.followup_fail_count += 1
                return 0, 0

            if selected_ids:
                items = [
                    item
                    for item in items
                    if str(item.get("record_id") or item.get("recordId") or "").strip()
                    in selected_ids
                ]

            matched_count = len(items)

            if not items:
                return matched_count, 0

            now_dt = datetime.now()
            hour_start = now_dt.replace(minute=0, second=0, microsecond=0)
            day_start = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)
            hour_sent = feishu.count_followup_sent_since(
                int(hour_start.timestamp() * 1000), int(now_dt.timestamp() * 1000)
            )
            day_sent = feishu.count_followup_sent_since(
                int(day_start.timestamp() * 1000), int(now_dt.timestamp() * 1000)
            )

            process_items = (
                items if manual_mode else items[: self.followup_cfg.batch_limit]
            )
            processed_count = 0
            for item in process_items:
                if self._should_abort():
                    return matched_count, processed_count

                record_id = str(
                    item.get("record_id") or item.get("recordId") or ""
                ).strip()
                if not record_id:
                    continue
                fields = item.get("fields", {})
                candidate = make_followup_candidate(item, fields)
                snapshot = build_snapshot_hash(
                    candidate, self.followup_cfg.prompt_version
                )

                is_already_sent = candidate.followup_status in {"已发送", "已回访"}
                if (
                    not manual_mode
                    and is_already_sent
                    and candidate.followup_snapshot_hash
                    and candidate.followup_snapshot_hash == snapshot
                ):
                    feishu.update_followup_state(
                        record_id,
                        {
                            "followup_status": "跳过",
                            "followup_reason": "命中幂等快照，跳过重复回访",
                        },
                    )
                    self.followup_skip_count += 1
                    processed_count += 1
                    continue

                decision = evaluate_candidate(
                    candidate,
                    self.followup_cfg,
                    now_dt,
                    hour_sent_count=hour_sent,
                    day_sent_count=day_sent,
                )
                if decision.decision == "skip":
                    feishu.update_followup_state(
                        record_id,
                        {
                            "followup_status": "跳过",
                            "followup_reason": f"{decision.reason_code}:{decision.reason_detail}",
                        },
                    )
                    self.followup_skip_count += 1
                    processed_count += 1
                    continue

                feishu.update_followup_state(
                    record_id,
                    {
                        "followup_status": "生成中",
                        "followup_snapshot": snapshot,
                        "followup_attempts": candidate.followup_attempts + 1,
                    },
                )

                default_prompt = self.llm_client._build_prompt(candidate)
                prompt_override = self._get_followup_prompt_override(record_id)
                request_prompt = prompt_override or default_prompt
                customer_name = candidate.nickname or candidate.phone or "未知客户"
                self._record_followup_request(
                    record_id=record_id,
                    customer=customer_name,
                    wechat_id=candidate.wechat_id,
                    prompt=request_prompt,
                    status="待请求",
                )

                msg_result = self.llm_client.compose(
                    candidate,
                    prompt_override=request_prompt,
                )
                request_status = "已请求"
                if msg_result.fallback_used:
                    request_status = "模板降级"
                self._record_followup_request(
                    record_id=record_id,
                    customer=customer_name,
                    wechat_id=candidate.wechat_id,
                    prompt=request_prompt,
                    status=request_status,
                )
                self.followup_generated_count += 1

                feishu.update_followup_state(
                    record_id,
                    {
                        "followup_status": "待发送",
                        "followup_message": msg_result.text,
                        "followup_reason": f"{msg_result.reason_code}:{msg_result.reason_detail}",
                    },
                )

                if self.followup_cfg.dry_run:
                    logger.info("回访dry-run：仅生成文案不发送 [{}]", record_id)
                    processed_count += 1
                    continue

                send_ok = False
                search_key = candidate.phone.strip()
                if not search_key:
                    feishu.update_followup_state(
                        record_id,
                        {
                            "followup_status": "失败",
                            "followup_reason": "missing_phone",
                        },
                    )
                    self.followup_fail_count += 1
                    processed_count += 1
                    continue
                try:
                    with self.wechat_lock:
                        send_ok = wechat.send_welcome_package(
                            [search_key],
                            [{"type": "text", "content": msg_result.text}],
                        )
                except Exception as exc:
                    logger.warning(
                        "回访发送异常 [{}] search_key={}: {}",
                        record_id,
                        search_key,
                        exc,
                    )

                if send_ok:
                    sent_at = datetime.now()
                    feishu.update_followup_state(
                        record_id,
                        {
                            "followup_status": "已发送",
                            "followup_last_sent_at": int(sent_at.timestamp() * 1000),
                            "followup_reason": "send_ok",
                        },
                    )
                    self.followup_sent_count += 1
                    hour_sent += 1
                    day_sent += 1
                    logger.info(
                        "回访发送成功 [{}] search_key={} wechat_id={} time={}",
                        record_id,
                        search_key,
                        candidate.wechat_id,
                        format_time(sent_at),
                    )
                    processed_count += 1
                else:
                    feishu.update_followup_state(
                        record_id,
                        {
                            "followup_status": "失败",
                            "followup_reason": "wechat_send_failed",
                        },
                    )
                    self.followup_fail_count += 1
                    processed_count += 1

            return matched_count, processed_count
        finally:
            if acquired:
                self._followup_run_lock.release()

    def _handle_passive_new_friends(self) -> None:
        """
        处理被动监控发现的新好友。

        新流程：
        1. 先处理'已添加'的好友
           - 点击"发消息"发送welcome
           - 删除好友记录
        2. 再处理'等待验证'的好友
           - 点击"前往验证" + "发消息"发送welcome
           - 删除好友记录
        """
        feishu = self.feishu
        wechat = self.wechat
        if feishu is None or wechat is None:
            return

        if self._should_abort():
            return

        with self.wechat_lock:
            # 使用新的通讯录扫描方法（内部已完成welcome和删除）
            count = wechat.scan_new_friends_via_contacts(
                feishu,
                self.welcome_enabled,
                self.welcome_steps,
                abort_check=self._should_abort,
            )
            if count > 0:
                logger.info("[被动监控] 本次扫描共处理 {} 个新好友", count)

    def _should_abort(self) -> bool:
        return self.stop_event.is_set() or self.pause_event.is_set()
