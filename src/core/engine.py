from __future__ import annotations

import json
import random
import requests
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, cast

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
        self.feishu_poll_interval: float = 5.0  # 飞书轮询间隔，默认5秒
        # 统计计数器
        self.apply_count = 0  # 申请处理数
        self.welcome_count = 0  # 欢迎发送数
        self.fail_count = 0  # 失败数
        self._co_initialized = False  # COM初始化状态

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
            while not self.stop_event.is_set():
                # 检查暂停状态
                if self.pause_event.is_set():
                    self.pause_event.wait(1)  # 暂停时每秒检查一次
                    continue

                self._handle_apply_queue(feishu, wechat)
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
                if self.pause_event.is_set():
                    self.pause_event.wait(1)  # 暂停时每秒检查一次
                    continue

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
                profile_win = wechat._search_and_open_profile(phone)

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
                relationship = wechat._detect_relationship_state(
                    [profile_win], timeout=self.relationship_timeout
                )
                logger.info("[申请队列] 手机:{}, 关系检测: {}", phone, relationship)

                if relationship == "friend":
                    # 已经是好友，直接发送welcome并更新为"已绑定"
                    logger.info("{} 已经是好友，直接发送welcome", phone)
                    self._send_welcome_and_update(
                        feishu, wechat, phone, None, record_id
                    )
                    self.apply_count += 1
                    continue

                if relationship == "stranger":
                    # 获取昵称（从已打开的资料卡）
                    nickname = wechat._extract_nickname_from_profile(profile_win)
                    logger.info("[申请队列] 获取到昵称: {}", nickname)

                    # 发送好友申请（资料卡已打开，直接点击添加）
                    with self.wechat_lock:
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
    ) -> None:
        """
        发送welcome并更新飞书状态。

        Args:
            feishu: 飞书客户端
            wechat: 微信RPA
            phone: 手机号/微信号
            name: 姓名（可选）
            record_id: 飞书记录ID
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
                send_ok = wechat.send_welcome_package(search_keys, self.welcome_steps)
        except Exception as exc:  # noqa: BLE001
            logger.warning("发送欢迎包异常 [{}]: {}", phone, exc)
            send_ok = False

        if send_ok:
            feishu.update_status(record_id, "已绑定")
            self.welcome_count += 1
        else:
            logger.warning("[{}] welcome发送失败，保持原状态", phone)
            self.fail_count += 1

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

        with self.wechat_lock:
            # 使用新的通讯录扫描方法（内部已完成welcome和删除）
            count = wechat.scan_new_friends_via_contacts(
                feishu, self.welcome_enabled, self.welcome_steps
            )
            if count > 0:
                logger.info("[被动监控] 本次扫描共处理 {} 个新好友", count)
