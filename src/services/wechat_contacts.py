"""
微信RPA通讯录操作模块
负责通讯录tab、新的朋友、好友验证等操作
"""

from __future__ import annotations

import re
import time
from typing import Optional, List, Any, Literal, TypedDict

import uiautomation as auto
from loguru import logger


class NewFriendItem(TypedDict):
    """新的朋友列表项数据结构"""

    name: str  # 昵称
    status: Literal["已添加", "等待验证"]  # 状态（微信UI显示）
    raw_text: str  # 原始文本
    control: Any  # 控件对象


class WeChatContactsOperations:
    """微信通讯录操作类"""

    def __init__(self, owner: Any):
        """
        初始化通讯录操作类

        Args:
            owner: 拥有此实例的WeChatRPA对象
        """
        self._owner = owner
        self._processed_nickname: Optional[str] = None  # 暂存刚发送welcome的昵称

    # ====================== Tab切换 ======================

    def _click_contacts_tab(self) -> bool:
        """点击侧边栏'通讯录' Tab"""
        return self._owner._click_button(
            "通讯录", timeout=2, search_depth=8, class_name="mmui::XTabBarItem"
        )

    def _return_to_chat_list(self) -> bool:
        """返回聊天列表界面"""
        return self._owner._click_button(
            "微信", timeout=2, search_depth=8, class_name="mmui::XTabBarItem"
        )

    # ====================== 新的朋友入口 ======================

    def _click_new_friends_entry(self) -> bool:
        """
        点击'新的朋友'入口。

        注意：只有收到好友请求时才会出现"新的朋友"入口，
        没有好友请求时找不到是正常情况，直接返回False即可。

        Returns:
            是否成功点击（False表示没有新的朋友，这是正常情况）
        """
        # 先检查是否已展开
        all_items = self._get_new_friends_items(check_only=True)
        if all_items:
            logger.debug("'新的朋友'列表已展开")
            return True

        # 尝试点击展开
        new_friends = self._owner._find_and_click_list_item(
            "新的朋友", timeout=1, search_depth=15
        )
        if new_friends:
            self._owner._random_delay(0.5, 1.0)
            return True

        # 备用：遍历查找
        main_win = self._owner._get_window(self._owner.WINDOW_NAME)
        if main_win:
            try:
                # 使用 GetDescendants 的安全方式
                descendants = getattr(main_win, "GetDescendants", None)
                if descendants:
                    for ctrl in descendants():
                        try:
                            if getattr(ctrl, "ControlTypeName", "") == "ListControl":
                                for child in ctrl.GetChildren():
                                    try:
                                        name = getattr(child, "Name", "") or ""
                                        cls = getattr(child, "ClassName", "") or ""
                                        if (
                                            name == "新的朋友"
                                            and cls == "mmui::ContactsCellGroupView"
                                        ):
                                            child.Click()
                                            self._owner._random_delay(0.5, 1.0)
                                            return True
                                    except Exception:
                                        continue
                        except Exception:
                            continue
            except Exception:
                pass

        # 没有找到"新的朋友"入口 - 这是正常情况，说明没有待处理的好友请求
        logger.debug("未找到'新的朋友'入口，可能是没有新的好友请求")
        return False

    def _get_new_friends_items(self, check_only: bool = False) -> List[NewFriendItem]:
        """
        获取'新的朋友'列表中的所有项，区分'已通过'和'等待验证'。

        Args:
            check_only: 如果为True，只检查是否存在，不返回列表

        Returns:
            NewFriendItem列表，每个元素包含昵称、状态和控件
        """
        items: List[NewFriendItem] = []

        # 查找通讯录列表容器
        list_container = self._owner._find_control(
            auto.ListControl, AutomationId="primary_table_.contact_list", searchDepth=12
        )
        if not list_container or not list_container.Exists(1):
            list_container = self._owner._find_control(
                auto.ListControl,
                ClassName="mmui::StickyHeaderRecyclerListView",
                searchDepth=12,
            )

        if not list_container or not list_container.Exists(1):
            return items

        try:
            children = list_container.GetChildren()
            for child in children:
                try:
                    item_name = getattr(child, "Name", "") or ""
                    # 解析状态：格式如 "昵称 等待验证" 或 "昵称 已添加"
                    if "等待验证" in item_name:
                        nickname = item_name.replace("等待验证", "").strip()
                        status: Literal["已添加", "等待验证"] = "等待验证"
                        items.append(
                            NewFriendItem(
                                name=nickname,
                                status=status,
                                raw_text=item_name,
                                control=child,
                            )
                        )
                    elif "已添加" in item_name:
                        nickname = item_name.replace("已添加", "").strip()
                        status: Literal["已添加", "等待验证"] = "已添加"
                        items.append(
                            NewFriendItem(
                                name=nickname,
                                status=status,
                                raw_text=item_name,
                                control=child,
                            )
                        )
                except Exception:
                    continue

            if not check_only:
                if items:
                    verified_count = sum(1 for i in items if i["status"] == "已添加")
                    pending_count = sum(1 for i in items if i["status"] == "等待验证")
                    logger.info(
                        "新的朋友列表: 已添加={}, 等待验证={}",
                        verified_count,
                        pending_count,
                    )
                else:
                    logger.debug("新的朋友列表为空")
        except Exception as e:
            if not check_only:
                logger.error("获取新的朋友列表失败: {}", e)

        return items

    def _get_verified_friends(self) -> List[NewFriendItem]:
        """
        筛选'已添加'的好友列表（我主动添加后对方通过的情况）。

        Returns:
            已添加状态的列表项
        """
        all_items = self._get_new_friends_items()
        return [item for item in all_items if item["status"] == "已添加"]

    def _get_pending_verification(self) -> List[NewFriendItem]:
        """
        筛选'等待验证'的列表项（对方添加我，需要我前往验证）。

        Returns:
            等待验证状态的列表项
        """
        all_items = self._get_new_friends_items()
        return [item for item in all_items if item["status"] == "等待验证"]

    def _find_item_by_nickname(self, nickname: str) -> Optional[NewFriendItem]:
        """
        通过昵称在"新的朋友"列表中找到对应的项。

        列表项 Name 格式: "昵称 已添加" 或 "昵称 等待验证"

        Args:
            nickname: 要匹配的昵称

        Returns:
            匹配的 NewFriendItem，未找到返回 None
        """
        items = self._get_new_friends_items()
        for item in items:
            # 检查 item["name"] 是否包含目标昵称
            if nickname in item["name"] or item["name"] in nickname:
                logger.debug("通过昵称找到列表项: {} -> {}", nickname, item["name"])
                return item
        logger.debug("未找到昵称对应的列表项: {}", nickname)
        return None

    # ====================== 验证流程 ======================

    def _open_new_friend_detail(self, item: NewFriendItem) -> bool:
        """点击列表项，进入详情页"""
        control = item.get("control")
        if control and control.Exists(1):
            control.Click()
            logger.debug("点击列表项成功: {}", item["name"])
            self._owner._random_delay()
            return True
        return False

    def _click_confirm_button(self) -> bool:
        """
        点击'前往验证'或'确定'按钮完成验证流程。

        对方加我时，需要点击"前往验证"按钮确认。
        """
        # 先尝试点击"前往验证"
        if self._owner._click_button(
            "前往验证", timeout=3, search_depth=15, class_name="mmui::XOutlineButton"
        ):
            self._owner._random_delay(0.5, 1.0)
            time.sleep(0.8)
            return True

        # 尝试点击"确定"
        if self._owner._click_button(
            "确定", timeout=3, search_depth=15, class_name="mmui::XOutlineButton"
        ):
            self._owner._random_delay(0.5, 1.0)
            time.sleep(0.8)
            return True

        # 备用：模糊匹配
        confirm_patterns = ["前往验证", "确定", "同意"]
        for pattern in confirm_patterns:
            if self._owner._click_button_by_name_contains(
                pattern, timeout=2, search_depth=15
            ):
                self._owner._random_delay(0.5, 1.0)
                time.sleep(0.8)
                return True

        logger.warning("未找到确认按钮")
        return False

    def _click_verify_button(self) -> bool:
        """
        点击'前往验证'按钮。

        Returns:
            是否成功点击
        """
        if self._owner._click_button(
            "前往验证", timeout=3, search_depth=15, class_name="mmui::XOutlineButton"
        ):
            self._owner._random_delay(0.5, 1.0)
            time.sleep(0.8)
            return True

        # 备用：模糊匹配
        if self._owner._click_button_by_name_contains(
            "前往验证", timeout=2, search_depth=15
        ):
            self._owner._random_delay(0.5, 1.0)
            time.sleep(0.8)
            return True

        logger.warning("未找到'前往验证'按钮")
        return False

    def _handle_verify_confirm_dialog(self) -> bool:
        """
        处理'前往验证'后的确认弹窗。

        点击"前往验证"按钮后会弹出一个确认对话框，需要点击"确定"完成验证。

        Returns:
            是否成功处理弹窗
        """
        # 等待弹窗出现
        time.sleep(0.5)

        # 尝试多种方式查找"确定"按钮

        # 方式1: 查找弹窗窗口中的"确定"按钮
        confirm_btn = self._owner._find_control(
            auto.ButtonControl,
            Name="确定",
            ClassName="mmui::XOutlineButton",
            searchDepth=15,
        )

        # 方式2: 查找任何包含"确定"的按钮
        if not confirm_btn or not confirm_btn.Exists(1):
            confirm_btn = self._owner._click_button(
                "确定", timeout=2, search_depth=15, class_name="mmui::XOutlineButton"
            )
            if confirm_btn:
                logger.debug("点击'确定'按钮成功")
                self._owner._random_delay(0.5, 1.0)
                time.sleep(1.0)
                return True

        # 方式3: 查找弹窗 WindowControl
        popup_win = self._owner._find_control(
            auto.WindowControl, ClassName="mmui::Popup", searchDepth=10
        )
        if popup_win and popup_win.Exists(1):
            confirm_btn = popup_win.ButtonControl(Name="确定", searchDepth=10)
            if confirm_btn.Exists(0.5):
                confirm_btn.Click()
                logger.debug("在弹窗中点击'确定'按钮成功")
                self._owner._random_delay(0.5, 1.0)
                time.sleep(1.0)
                return True

        # 方式4: 查找 MessageBox 风格的窗口
        msgbox_win = self._owner._find_control(
            auto.WindowControl, RegexName=".*确认.*|.*验证.*", searchDepth=10
        )
        if msgbox_win and msgbox_win.Exists(0.5):
            confirm_btn = msgbox_win.ButtonControl(Name="确定", searchDepth=5)
            if confirm_btn.Exists(0.3):
                confirm_btn.Click()
                logger.debug("在消息框中点击'确定'按钮成功")
                self._owner._random_delay(0.5, 1.0)
                time.sleep(1.0)
                return True

        # 方式5: 通用方式查找所有"确定"按钮
        main_win = self._owner._get_window(self._owner.WINDOW_NAME)
        if main_win:
            try:
                descendants = getattr(main_win, "GetDescendants", None)
                if descendants:
                    for ctrl in descendants():
                        try:
                            if getattr(ctrl, "ControlTypeName", "") == "ButtonControl":
                                name = getattr(ctrl, "Name", "") or ""
                                cls = getattr(ctrl, "ClassName", "") or ""
                                if name == "确定" and "Outline" in cls:
                                    ctrl.Click()
                                    logger.debug("通过遍历找到并点击'确定'按钮")
                                    self._owner._random_delay(0.5, 1.0)
                                    time.sleep(1.0)
                                    return True
                        except Exception:
                            continue
            except Exception:
                pass

        logger.warning("未找到确认弹窗中的'确定'按钮，可能弹窗已关闭或结构变化")
        return True  # 弹窗可能已经自动关闭，返回True继续流程

    def _extract_wechat_id_from_profile(self) -> Optional[str]:
        """从资料卡片中提取微信号"""
        time.sleep(0.8)  # 减少等待时间

        main_win = self._owner._get_window(self._owner.WINDOW_NAME)
        if not main_win.Exists(1):
            logger.debug("未找到微信主窗口")
            return None

        def collect_controls(
            control: Any, depth: int = 0, max_depth: int = 50
        ) -> List[Any]:
            if depth > max_depth:
                return []
            result = [control]
            try:
                for child in control.GetChildren():
                    result.extend(collect_controls(child, depth + 1, max_depth))
            except Exception:
                pass
            return result

        all_controls = collect_controls(main_win)

        # 查找 ContactProfileTextView 控件
        profile_text_views = []
        for ctrl in all_controls:
            try:
                ctrl_class = getattr(ctrl, "ClassName", "") or ""
                if "ContactProfileTextView" in ctrl_class:
                    ctrl_automation_id = getattr(ctrl, "AutomationId", "") or ""
                    ctrl_name = getattr(ctrl, "Name", "") or ""
                    profile_text_views.append(
                        {
                            "name": ctrl_name,
                            "automation_id": ctrl_automation_id,
                        }
                    )
            except Exception:
                continue

        # 筛选微信号
        for item in profile_text_views:
            ctrl_name = item["name"]
            ctrl_automation_id = item["automation_id"]

            if "basic_line_view" in ctrl_automation_id and ctrl_automation_id.endswith(
                "ContactProfileTextView"
            ):
                if re.match(r"^[A-Za-z0-9_.-]{4,20}$", ctrl_name):
                    logger.debug(
                        "提取到微信号: {} (AutomationId={})",
                        ctrl_name,
                        ctrl_automation_id,
                    )
                    return ctrl_name

        logger.debug("未找到有效的微信号")
        return None

    def _get_wechat_id_with_wait(self, timeout: float = 15.0) -> Optional[str]:
        """
        等待并获取微信号，带超时控制。

        Args:
            timeout: 超时时间（秒）

        Returns:
            微信号字符串，超时返回None
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            wechat_id = self._extract_wechat_id_from_profile()
            if wechat_id:
                logger.debug("成功提取微信号: {}", wechat_id)
                return wechat_id
            time.sleep(0.5)

        logger.warning("等待 {} 秒未能提取到微信号", timeout)
        return None

    # ====================== 处理入口 ======================

    def _click_send_message_button(self) -> bool:
        """
        在右侧资料面板中点击'发消息'按钮。

        按钮控件信息：
        - Name: "发消息"
        - AutomationId: "fixed_height_v_view.content_v_view.ContactProfileBottomUi.foot_button_view.chat_img_button"
        - ClassName: "mmui::ContactProfileBottomButton"
        """
        # 方法1: 通过 AutomationId 精确查找
        send_btn = self._owner._find_control(
            auto.ButtonControl,
            AutomationId="fixed_height_v_view.content_v_view.ContactProfileBottomUi.foot_button_view.chat_img_button",
            searchDepth=20,
        )
        if send_btn and send_btn.Exists(1):
            send_btn.Click()
            logger.debug("点击'发消息'按钮成功")
            self._owner._random_delay()
            return True

        # 方法2: 通过 Name 和 ClassName 查找
        send_btn = self._owner._find_control(
            auto.ButtonControl,
            Name="发消息",
            ClassName="mmui::ContactProfileBottomButton",
            searchDepth=20,
        )
        if send_btn and send_btn.Exists(1):
            send_btn.Click()
            logger.debug("点击'发消息'按钮成功")
            self._owner._random_delay()
            return True

        # 方法3: 备用 - 通过按钮名称模糊查找
        if self._owner._click_button(
            "发消息",
            timeout=3,
            search_depth=15,
            class_name="mmui::ContactProfileBottomButton",
        ):
            return True

        logger.warning("未找到'发消息'按钮")
        return False

    def _right_click_and_delete(self, item: NewFriendItem) -> bool:
        """
        右键点击列表项，在弹出菜单中点击"删除"。

        控件信息：
        - 好友列表项: ListItemControl, ClassName: mmui::XTableCell
        - 右键菜单: WindowControl, Name: "Weixin", ClassName: mmui::XMenu
        - 删除菜单项: MenuItemControl, Name: "删除", ClassName: mmui::XMenuView

        Args:
            item: 要删除的好友列表项

        Returns:
            是否删除成功
        """
        control = item.get("control")
        if not control or not control.Exists(1):
            logger.warning("列表项控件不存在，无法删除")
            return False

        # 1. 右键点击列表项
        try:
            control.RightClick()
            logger.debug("右键点击列表项: {}", item["name"])
            self._owner._random_delay(0.3, 0.5)
        except Exception as e:
            logger.warning("右键点击失败: {}", e)
            return False

        # 2. 查找右键菜单中的"删除"项
        delete_menu = self._owner._find_control(
            auto.MenuItemControl,
            Name="删除",
            ClassName="mmui::XMenuView",
            searchDepth=10,
        )

        # 如果找不到，尝试通过 WindowControl 查找
        if not delete_menu or not delete_menu.Exists(0.5):
            menu_win = self._owner._find_control(
                auto.WindowControl,
                Name="Weixin",
                ClassName="mmui::XMenu",
                searchDepth=5,
            )
            if menu_win and menu_win.Exists(0.5):
                delete_menu = menu_win.MenuItemControl(Name="删除", searchDepth=10)

        if delete_menu and delete_menu.Exists(0.5):
            try:
                delete_menu.Click()
                logger.info("点击'删除'菜单项成功: {}", item["name"])
                self._owner._random_delay(0.5, 1.0)
                return True
            except Exception as e:
                logger.warning("点击删除菜单项失败: {}", e)
                return False

        logger.warning("未找到'删除'菜单项")
        # 按ESC关闭菜单
        try:
            auto.SendKeys("{Esc}")
        except Exception:
            pass
        return False

    def _delete_by_stored_nickname(self, feishu) -> bool:
        """
        通过暂存的昵称删除"新的朋友"列表中的记录。

        流程：
        1. 检查是否有暂存的昵称
        2. 通过昵称更新飞书状态为"已绑定"
        3. 返回"新的朋友"列表
        4. 通过昵称找到列表项
        5. 右键删除
        6. 清空暂存的昵称

        Args:
            feishu: 飞书客户端实例，用于更新状态

        Returns:
            是否删除成功
        """
        if not self._processed_nickname:
            logger.warning("没有暂存的昵称，无法删除")
            return False

        nickname = self._processed_nickname
        logger.info("通过昵称删除: {}", nickname)

        # ========== 更新飞书状态为"已绑定" ==========
        try:
            items = feishu.search_by_nickname(nickname)
            if items:
                # 优先匹配"已申请"状态的记录
                matched_item = None
                for item in items:
                    record_id = feishu._extract_record_id(item)
                    status = item.get("fields", {}).get("微信绑定状态", "")
                    if status == "已申请":
                        matched_item = (record_id, item)
                        break

                # 如果没找到"已申请"状态的，匹配任意状态的
                if not matched_item and items:
                    record_id = feishu._extract_record_id(items[0])
                    matched_item = (record_id, items[0])

                if matched_item:
                    record_id, _ = matched_item
                    feishu.update_status(record_id, "已绑定")
                    logger.info(
                        "飞书状态已更新为'已绑定': {} (record_id={})",
                        nickname,
                        record_id,
                    )
            else:
                logger.warning("未在飞书中找到昵称对应的记录: {}", nickname)
        except Exception as e:
            logger.warning("更新飞书状态失败: {} - {}", nickname, e)
        # ===========================================

        # 返回"新的朋友"列表
        self._owner._activate_window()
        self._click_contacts_tab()
        self._click_new_friends_entry()
        self._owner._random_delay(0.5, 1.0)

        # 通过昵称找到列表项
        item = self._find_item_by_nickname(nickname)
        if not item:
            logger.warning("未找到昵称对应的列表项: {}", nickname)
            self._processed_nickname = None
            return False

        # 右键删除
        success = self._right_click_and_delete(item)
        self._processed_nickname = None
        return success

    def _process_verified_friend(
        self,
        item: NewFriendItem,
        feishu,
        welcome_enabled: bool,
        welcome_steps: List[dict[str, str | None]],
    ) -> bool:
        """
        处理'已添加'的好友（我主动添加后对方通过）。

        流程：
        1. 点击列表项打开右侧资料面板
        2. 获取微信号
        3. 写入飞书（微信号列=微信号，昵称列=昵称，状态=已绑定）
        4. 点击"发消息"进入聊天
        5. 发送welcome，暂存昵称
        6. 返回"新的朋友"列表
        7. 通过昵称找到记录并删除
        8. 返回聊天列表

        Args:
            item: 好友列表项
            feishu: 飞书客户端实例
            welcome_enabled: 是否启用欢迎包
            welcome_steps: 欢迎包步骤

        Returns:
            是否处理成功
        """
        # 清洗昵称：取"我"前面的部分，"我"及之后的都删除
        raw_nickname = item["name"]
        if "我" in raw_nickname:
            idx = raw_nickname.find("我")
            nickname = raw_nickname[:idx].strip()
        else:
            nickname = raw_nickname
        logger.info("[已添加] 处理好友: {} (原始: {})", nickname, raw_nickname)

        # 1. 点击列表项打开右侧资料面板
        if not self._open_new_friend_detail(item):
            logger.warning("[已添加] 无法进入详情页: {}", nickname)
            return False

        # ========== 2-3. 获取微信号并写入飞书（点击发消息之前） ==========
        wechat_id = self._get_wechat_id_with_wait(timeout=15.0)
        if wechat_id:
            try:
                # 写入飞书：微信号字段=微信号，状态=已绑定
                feishu.upsert_contact_profile(
                    wechat_id=wechat_id, nickname=nickname, status="已绑定"
                )
                logger.info(
                    "[已添加] 飞书写入成功: 微信号={}, 昵称={}, 状态=已绑定",
                    wechat_id,
                    nickname,
                )
            except Exception as e:
                logger.warning("[已添加] 飞书写入失败: {} - {}", nickname, e)
        else:
            logger.warning("[已添加] 未能获取到微信号，跳过飞书写入: {}", nickname)
        # =================================================================

        # 4. 点击"发消息"按钮进入聊天
        if not self._click_send_message_button():
            logger.warning("[已添加] 点击'发消息'按钮失败: {}", nickname)
            return False

        # 5. 发送welcome（已在聊天窗口中，already_in_chat=True）
        if welcome_enabled and welcome_steps:
            self._owner.send_welcome_package(
                [nickname], welcome_steps, already_in_chat=True
            )
            self._processed_nickname = nickname  # 暂存昵称用于删除

        # 6. 通过昵称删除（会返回"新的朋友"列表再删除）
        self._delete_by_stored_nickname(feishu)

        # 7. 返回聊天列表
        self._return_to_chat_list()

        return True

    def _process_pending_verification(
        self,
        item: NewFriendItem,
        feishu,
        welcome_enabled: bool,
        welcome_steps: List[dict[str, str | None]],
    ) -> bool:
        """
        处理'等待验证'的项（对方加我，需要我前往验证）。

        流程：
        1. 点击列表项打开详情页
        2. 点击"前往验证"按钮
        3. 处理确认弹窗（点击"确定"）
        4. 获取微信号
        5. 写入飞书（微信号列=微信号，昵称列=昵称，状态=已绑定）
        6. 点击"发消息"进入聊天
        7. 发送welcome，暂存昵称
        8. 返回"新的朋友"列表
        9. 通过昵称找到记录并删除
        10. 返回聊天列表

        Args:
            item: 待验证列表项
            feishu: 飞书客户端实例
            welcome_enabled: 是否启用欢迎包
            welcome_steps: 欢迎包步骤

        Returns:
            是否处理成功
        """
        # 清洗昵称：取"我"前面的部分，"我"及之后的都删除
        raw_nickname = item["name"]
        if "我" in raw_nickname:
            idx = raw_nickname.find("我")
            nickname = raw_nickname[:idx].strip()
        else:
            nickname = raw_nickname
        logger.info("[待验证] 处理好友: {} (原始: {})", nickname, raw_nickname)

        # 1. 点击列表项打开详情页
        if not self._open_new_friend_detail(item):
            logger.warning("[待验证] 无法进入详情页: {}", nickname)
            return False

        # 2. 点击"前往验证"按钮
        if not self._click_verify_button():
            logger.warning("[待验证] 点击前往验证失败: {}", nickname)
            return False

        # 3. 处理确认弹窗（点击"确定"）
        if not self._handle_verify_confirm_dialog():
            logger.warning("[待验证] 处理确认弹窗失败: {}", nickname)
            # 继续尝试，可能弹窗已自动关闭

        # ========== 4-5. 获取微信号并写入飞书（点击发消息之前） ==========
        wechat_id = self._get_wechat_id_with_wait(timeout=15.0)
        if wechat_id:
            try:
                # 写入飞书：微信号字段=微信号，状态=已绑定
                feishu.upsert_contact_profile(
                    wechat_id=wechat_id, nickname=nickname, status="已绑定"
                )
                logger.info(
                    "[待验证] 飞书写入成功: 微信号={}, 昵称={}, 状态=已绑定",
                    wechat_id,
                    nickname,
                )
            except Exception as e:
                logger.warning("[待验证] 飞书写入失败: {} - {}", nickname, e)
        else:
            logger.warning("[待验证] 未能获取到微信号，跳过飞书写入: {}", nickname)
        # =================================================================

        # 6. 点击"发消息"按钮进入聊天
        if not self._click_send_message_button():
            logger.warning("[待验证] 点击'发消息'按钮失败: {}", nickname)
            return False

        # 7. 发送welcome（已在聊天窗口中，already_in_chat=True）
        if welcome_enabled and welcome_steps:
            self._owner.send_welcome_package(
                [nickname], welcome_steps, already_in_chat=True
            )
            self._processed_nickname = nickname  # 暂存昵称用于删除

        # 8. 通过昵称删除（会返回"新的朋友"列表再删除）
        self._delete_by_stored_nickname(feishu)

        # 9. 返回聊天列表
        self._return_to_chat_list()

        return True

    # ====================== 扫描入口 ======================

    def scan_new_friends_via_contacts(
        self,
        feishu,
        welcome_enabled: bool,
        welcome_steps: List[Any],
    ) -> int:
        """
        通过通讯录-新的朋友扫描并处理新好友。

        处理流程：
        1. 先处理'已添加'的好友（我主动添加后对方通过）
           - 发送welcome
           - 删除好友记录
        2. 再处理'等待验证'的项（对方加我）
           - 前往验证
           - 发送welcome
           - 删除好友记录

        Args:
            feishu: 飞书客户端实例，用于状态更新
            welcome_enabled: 是否启用欢迎包
            welcome_steps: 欢迎包步骤

        Returns:
            处理成功的好友数量
        """
        if not self._owner._activate_window():
            return 0

        # 点击通讯录
        if not self._click_contacts_tab():
            return 0

        # 点击新的朋友
        if not self._click_new_friends_entry():
            return 0

        # 获取所有项
        all_items = self._get_new_friends_items()
        if not all_items:
            logger.debug("新的朋友列表为空")
            self._return_to_chat_list()
            return 0

        # 分离两类好友
        verified_friends = self._get_verified_friends()
        pending_items = self._get_pending_verification()

        logger.info(
            "开始处理新好友: 已添加={}, 待验证={}",
            len(verified_friends),
            len(pending_items),
        )

        processed_count = 0

        # ====================== 第一阶段：处理'已添加'的好友 ======================
        for idx, item in enumerate(verified_friends, 1):
            try:
                logger.info(
                    "[阶段1/2] [{}/{}] 处理已添加好友", idx, len(verified_friends)
                )
                if self._process_verified_friend(
                    item, feishu, welcome_enabled, welcome_steps
                ):
                    processed_count += 1
            except Exception as e:
                logger.error("[已添加] 处理异常: {} - {}", item["name"], e)
            finally:
                # 返回并继续下一个
                try:
                    self._return_to_chat_list()
                except Exception:
                    pass
                if idx < len(verified_friends):
                    self._owner._activate_window()
                    self._click_contacts_tab()
                    self._click_new_friends_entry()

        # ====================== 第二阶段：处理'等待验证'的好友 ======================
        for idx, item in enumerate(pending_items, 1):
            try:
                logger.info("[阶段2/2] [{}/{}] 处理待验证好友", idx, len(pending_items))
                if self._process_pending_verification(
                    item, feishu, welcome_enabled, welcome_steps
                ):
                    processed_count += 1
            except Exception as e:
                logger.error("[待验证] 处理异常: {} - {}", item["name"], e)
            finally:
                # 返回并继续下一个
                try:
                    self._return_to_chat_list()
                except Exception:
                    pass
                if idx < len(pending_items):
                    self._owner._activate_window()
                    self._click_contacts_tab()
                    self._click_new_friends_entry()

        # 返回聊天列表
        try:
            self._return_to_chat_list()
        except Exception:
            pass

        logger.info("扫描完成，共处理 {} 个新好友", processed_count)
        return processed_count
