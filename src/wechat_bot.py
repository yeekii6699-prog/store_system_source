"""
基于 uiautomation 的微信桌面端自动化。
已根据用户截图（独立弹窗模式 + 申请添加朋友新弹窗）进行最终适配。
增加：资料卡按钮加载延迟的智能等待逻辑。
"""

from __future__ import annotations

import time
from typing import Optional

import uiautomation as auto
from loguru import logger


class WeChatRPA:
    """
    封装微信常用的窗口操作，便于在业务层调用。
    """

    def __init__(self, exec_path: Optional[str] = None) -> None:
        self.exec_path = exec_path

    def activate_window(self) -> bool:
        """
        唤起微信主窗口到前台，若未启动则尝试启动。
        """
        win = auto.WindowControl(searchDepth=1, Name="微信")
        if not win.Exists(0, 0):
            if not self.exec_path:
                logger.error("未找到微信窗口，且未配置 WECHAT_EXEC_PATH")
                return False
            logger.info("尝试启动微信客户端: {}", self.exec_path)
            import subprocess

            subprocess.Popen(self.exec_path)
            time.sleep(3)
            win = auto.WindowControl(searchDepth=1, Name="微信")

        if win.Exists(0, 0):
            win.SetActive()
            win.SetFocus()
            return True

        logger.error("无法激活微信窗口")
        return False

    def _click_button(self, parent, name: str, timeout: float = 3.0) -> bool:
        """
        在给定父控件下点击按钮，封装等待逻辑。
        """
        # 优先找 ButtonControl
        btn = parent.ButtonControl(Name=name, searchDepth=10)
        if not btn.Exists(0):
            # 备用：有时候按钮可能被识别为普通 Control 或 Image
            btn = parent.Control(Name=name, searchDepth=10)
            
        if btn.Exists(timeout):
            btn.Click()
            return True
        return False

    def add_friend(self, phone: str, verify_msg: str = "") -> str:
        """
        通过手机号添加好友。
        verify_msg: 验证语
        """
        if not self.activate_window():
            return "failed"

        main = auto.WindowControl(searchDepth=1, Name="微信")
        
        # 1. 定位搜索框
        search_box = main.EditControl(Name="搜索", searchDepth=15)
        if not search_box.Exists(3):
            search_box = main.EditControl(Name="Search", searchDepth=15)
            if not search_box.Exists(1):
                logger.error("未找到搜索输入框")
                return "failed"

        # 2. 输入手机号
        search_box.Click()
        time.sleep(0.2)
        search_box.SendKeys("{Ctrl}a")
        time.sleep(0.1)
        search_box.SendKeys("{Delete}")
        search_box.SendKeys(phone)
        time.sleep(1.5)

        # 3. 点击搜索结果（触发“添加朋友”弹窗）
        search_result_list = main.ListControl(AutomationId="search_list")
        target_item = None
        
        if search_result_list.Exists(1):
            # 优先找“网络查找”
            target_item = search_result_list.ListItemControl(Name="网络查找手机/QQ号")
            if not target_item.Exists(0):
                 target_item = search_result_list.ListItemControl(SubName="网络查找")
            # 如果没找到网络查找，直接点第一个（可能是精准匹配的人）
            if not target_item.Exists(0):
                 target_item = search_result_list.ListItemControl(searchDepth=1)

        if target_item and target_item.Exists(0):
            target_item.Click()
        else:
            # 兜底：直接回车
            search_box.SendKeys("{Enter}")
            
        # 这里不需要死等，弹窗出来需要时间，我们在下一步用 Exists 配合循环来等

        # =================================================
        # 4. 核心逻辑：处理“添加朋友”资料卡弹窗（智能等待版）
        # =================================================

        # 捕捉名为“添加朋友”的独立窗口
        contact_win = auto.WindowControl(Name="添加朋友")
        
        # 4.1 等待弹窗出现
        if not contact_win.Exists(5): # 给它最多5秒弹出来
            # 备用逻辑：如果窗口没弹出来，检查是不是在主界面直接显示了
            if main.EditControl(AutomationId="chat_input_field", searchDepth=20).Exists(0):
                logger.info("未弹窗，但检测到聊天输入框，判定已是好友")
                return "exists"
            else:
                 logger.warning("未检测到'添加朋友'弹窗")
                 return "failed"

        logger.info("捕获到资料卡弹窗，开始轮询按钮状态...")
        
        # 4.2 智能轮询：等待下方按钮加载 (解决卡顿问题)
        # 也就是：每隔 0.5 秒看一眼，持续 5 秒，直到“发消息”或“添加到通讯录”出现
        
        status = "unknown"
        end_time = time.time() + 8.0 # 最多等 8 秒
        
        while time.time() < end_time:
            # 【判定 A：已经是好友】 -> 找 "发消息"
            if contact_win.ButtonControl(Name="发消息", searchDepth=10).Exists(0):
                logger.info("检测到'发消息'按钮，判定已是好友")
                status = "exists"
                break
            
            # 【判定 B：未添加】 -> 找 "添加到通讯录"
            add_btn = contact_win.ButtonControl(Name="添加到通讯录", searchDepth=10)
            if add_btn.Exists(0):
                logger.info("检测到'添加到通讯录'按钮，点击添加")
                add_btn.Click()
                status = "adding"
                break
            
            # 如果都没找到，说明还在加载，或者对方设置了隐私
            time.sleep(0.5)

        # 4.3 处理轮询结果
        if status == "exists":
            contact_win.SendKeys("{Esc}") # 关闭弹窗
            return "exists"
            
        elif status == "adding":
            # 已经点击了添加，进入下一步处理新弹窗
            pass 
            
        else:
            logger.warning("资料卡加载超时，未找到操作按钮（可能是隐私设置或网络问题）")
            contact_win.SendKeys("{Esc}") # 关闭弹窗防止遮挡
            return "failed"

        # =================================================
        # 5. 核心逻辑：处理“申请添加朋友”验证弹窗（截图2）
        # =================================================
        time.sleep(1.0) # 点击添加后，等新窗口弹出来
        
        # 截图2显示的窗口名叫 "申请添加朋友"
        apply_win = auto.WindowControl(Name="申请添加朋友")
        
        if apply_win.Exists(5): # 多给点时间加载
            logger.info("捕获到'申请添加朋友'弹窗")
            
            # 截图显示底部绿色按钮叫 "确定"
            confirm_btn = apply_win.ButtonControl(Name="确定", searchDepth=10)
            if not confirm_btn.Exists(0):
                confirm_btn = apply_win.ButtonControl(Name="发送", searchDepth=10)
            
            if confirm_btn.Exists(1):
                logger.info("点击申请弹窗中的确定/发送按钮")
                confirm_btn.Click()
                time.sleep(0.5)
            else:
                logger.error("在申请弹窗中未找到确定/发送按钮")
                return "failed"
        else:
            # 极少数情况，不需要验证直接添加成功，或者窗口名不对
            logger.warning("点击添加后，未检测到'申请添加朋友'弹窗，可能已直接发送或不需要验证")
        
        logger.info("已完成好友申请操作: {}", phone)
        return "added"

    def send_msg(self, remark_name: str, msg: str) -> bool:
        """
        按备注名搜索好友并发送文本消息。
        """
        if not self.activate_window():
            return False

        main = auto.WindowControl(searchDepth=1, Name="微信")
        
        # 1. 搜索好友
        search_box = main.EditControl(Name="搜索", searchDepth=15)
        if not search_box.Exists(3):
            logger.error("找不到搜索框")
            return False

        search_box.Click()
        search_box.SendKeys("{Ctrl}a")
        time.sleep(0.1)
        search_box.SendKeys("{Delete}")
        search_box.SendKeys(remark_name)
        time.sleep(1.0)
        search_box.SendKeys("{Enter}")
        time.sleep(0.5)

        # 2. 定位聊天输入框
        input_box = main.EditControl(AutomationId="chat_input_field", searchDepth=20)
        
        if not input_box.Exists(2):
            logger.error("未找到聊天输入框")
            return False

        input_box.Click()
        input_box.SendKeys(msg)
        time.sleep(0.2)
        input_box.SendKeys("{ENTER}")
        
        logger.info("已向 {} 发送消息", remark_name)
        return True