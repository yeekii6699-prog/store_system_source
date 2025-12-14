import os

# 修复 SendKeys 语法的最终代码
file_content = r'''"""
src/wechat_bot.py
基于 uiautomation 的微信 RPA 核心库 (V2 修正版)
核心修复：
1. 按键语法：将所有 '^v' 替换为 '{Ctrl}v'，修复粘贴失败的问题。
2. 内存管理：保留了 ctypes 手动管理剪贴板内存的逻辑，防止报错。
3. 数据清洗：保留了 keyword 强转 string 的逻辑。
"""

from __future__ import annotations

import time
import struct
import ctypes
from pathlib import Path
from typing import Optional, Sequence, Literal

import uiautomation as auto
from loguru import logger

# 依赖检查
try:
    import pyperclip
except ImportError:
    logger.error("缺少 pyperclip 依赖，请运行: pip install pyperclip")
    pyperclip = None

try:
    import win32clipboard
    import win32con
except ImportError:
    win32clipboard = None
    win32con = None
    logger.warning("未安装 pywin32，图片发送功能将不可用")


class WeChatRPA:
    WINDOW_NAME = "微信"
    PROFILE_TITLES = ("详细资料", "基本资料", "资料", "个人信息", "添加朋友")

    def __init__(self, exec_path: Optional[str] = None):
        self.exec_path = exec_path

    def _activate_window(self) -> bool:
        """强制激活微信窗口到前台"""
        win = auto.WindowControl(searchDepth=1, Name=self.WINDOW_NAME)
        if not win.Exists(0, 0):
            if self.exec_path:
                import subprocess
                subprocess.Popen(self.exec_path)
                time.sleep(3)
                win = auto.WindowControl(searchDepth=1, Name=self.WINDOW_NAME)
            else:
                logger.error("未找到微信窗口且未配置启动路径")
                return False
        
        win.SetActive()
        win.SetFocus()
        return True

    def _copy_image_to_clipboard(self, image_path: str) -> bool:
        """
        [底层重写] 将图片文件以 CF_HDROP 格式写入剪贴板
        使用 ctypes 手动管理内存，解决 'bytes-like object required' 报错
        """
        if not win32clipboard or not win32con:
            return False
            
        path_obj = Path(image_path).resolve()
        if not path_obj.exists():
            logger.error(f"图片不存在: {image_path}")
            return False

        try:
            files = [str(path_obj)]
            files_str = "\0".join(files) + "\0\0"
            files_bytes = files_str.encode("utf-16le")
            header = struct.pack("IiiII", 20, 0, 0, 0, 1)
            data = header + files_bytes
            h_global = ctypes.windll.kernel32.GlobalAlloc(0x0002, len(data))
            if not h_global:
                return False
            ptr = ctypes.windll.kernel32.GlobalLock(h_global)
            ctypes.memmove(ptr, data, len(data))
            ctypes.windll.kernel32.GlobalUnlock(h_global)
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_HDROP, h_global)
            win32clipboard.CloseClipboard()
            return True
        except Exception as e:
            logger.error(f"写入剪贴板底层错误: {e}")
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            return False

    def _clean_keyword(self, keyword) -> str:
        """数据清洗"""
        if isinstance(keyword, (list, tuple)):
            return str(keyword[0]) if len(keyword) > 0 else ""
        return str(keyword)

    def _search_and_open_profile(self, keyword) -> Optional[auto.WindowControl]:
        """搜索关键词并打开资料卡"""
        keyword = self._clean_keyword(keyword)
        if not keyword:
            return None

        if not self._activate_window():
            return None
            
        main = auto.WindowControl(searchDepth=1, Name=self.WINDOW_NAME)
        search_box = main.EditControl(Name="搜索", searchDepth=15)
        if not search_box.Exists(0.5):
            search_box = main.EditControl(Name="Search", searchDepth=15)
        if not search_box.Exists(2):
            return None
            
        if pyperclip:
            search_box.Click()
            time.sleep(0.1)
            search_box.SendKeys("{Ctrl}a{Delete}")
            pyperclip.copy(keyword)
            time.sleep(0.1)
            search_box.SendKeys("{Ctrl}v")
        else:
            search_box.Click()
            search_box.SendKeys("{Ctrl}a{Delete}")
            search_box.SendKeys(keyword)

        time.sleep(1.5) 
        
        search_list = main.ListControl(AutomationId='search_list')
        clicked = False
        if search_list.Exists(0.5):
            target = search_list.ListItemControl(SubName="网络查找")
            if target.Exists(0):
                target.Click()
                clicked = True
            else:
                first = search_list.ListItemControl(foundIndex=1)
                if first.Exists(0):
                    first.Click()
                    clicked = True
        
        if not clicked:
            search_box.SendKeys("{Enter}")
        else:
            time.sleep(0.2)
            search_box.SendKeys("{Enter}")
            
        profile_win = None
        end_time = time.time() + 4
        while time.time() < end_time:
            for title in self.PROFILE_TITLES:
                win = auto.WindowControl(Name=title, searchDepth=1)
                if win.Exists(0):
                    profile_win = win
                    break
            if profile_win:
                break
            time.sleep(0.3)
            
        return profile_win

    def check_relationship(self, keyword) -> Literal["friend", "stranger", "unknown"]:
        """检查关系状态"""
        keyword = self._clean_keyword(keyword)
        profile_win = self._search_and_open_profile(keyword)
        if not profile_win:
            return "unknown"
        
        result = "unknown"
        try:
            end_time = time.time() + 3
            while time.time() < end_time:
                if profile_win.ButtonControl(Name="发消息", searchDepth=10).Exists(0):
                    result = "friend"
                    break
                if profile_win.ButtonControl(Name="添加到通讯录", searchDepth=10).Exists(0):
                    result = "stranger"
                    break
                time.sleep(0.3)
        finally:
            if profile_win.Exists(0):
                profile_win.SendKeys("{Esc}")
        return result

    def apply_friend(self, keyword) -> bool:
        """执行申请操作"""
        keyword = self._clean_keyword(keyword)
        profile_win = self._search_and_open_profile(keyword)
        if not profile_win:
            return False
        
        success = False
        try:
            add_btn = profile_win.ButtonControl(Name="添加到通讯录", searchDepth=10)
            if add_btn.Exists(2):
                add_btn.Click()
                time.sleep(1)
                for win_name in ("申请添加朋友", "发送好友申请", "好友验证"):
                    win = auto.WindowControl(Name=win_name)
                    if win.Exists(0.5):
                        for btn_name in ("确定", "发送", "Send"):
                            btn = win.ButtonControl(Name=btn_name)
                            if btn.Exists(0):
                                btn.Click()
                                success = True
                                break
                        break
                if not success and not add_btn.Exists(0):
                    success = True
        finally:
            if profile_win.Exists(0):
                profile_win.SendKeys("{Esc}")
        return success

    def send_welcome_package(self, keyword, steps: Sequence[dict]) -> bool:
        """发送欢迎包"""
        keyword = self._clean_keyword(keyword)
        if not pyperclip:
            return False

        profile_win = self._search_and_open_profile(keyword)
        if not profile_win:
            return False
            
        try:
            msg_btn = None
            for _ in range(3):
                msg_btn = profile_win.ButtonControl(Name="发消息", searchDepth=10)
                if msg_btn.Exists(0):
                    break
                time.sleep(0.5)
            
            if msg_btn and msg_btn.Exists(0):
                msg_btn.Click()
                time.sleep(0.8)
            else:
                return False
        finally:
            if profile_win.Exists(0):
                profile_win.SendKeys("{Esc}")

        self._activate_window()
        
        logger.info(f"开始向 [{keyword}] 发送欢迎包...")
        for i, step in enumerate(steps):
            try:
                msg_type = step.get("type")
                content = step.get("content") or step.get("path") or step.get("url")
                if not content:
                    continue
                content = str(content)
                if msg_type == "text":
                    pyperclip.copy(content)
                    auto.SendKeys('{Ctrl}v')
                    time.sleep(0.3)
                    auto.SendKeys('{Enter}')
                elif msg_type == "link":
                    title = step.get("title", "")
                    text = f"{title}\n{content}" if title else content
                    pyperclip.copy(text)
                    auto.SendKeys('{Ctrl}v')
                    time.sleep(0.3)
                    auto.SendKeys('{Enter}')
                elif msg_type == "image":
                    if self._copy_image_to_clipboard(content):
                        auto.SendKeys('{Ctrl}v')
                        time.sleep(0.8)
                        auto.SendKeys('{Enter}')
                    else:
                        logger.error(f"图片复制失败: {content}")
                time.sleep(1.0)
            except Exception as e:
                logger.error(f"发送步骤 {i+1} 失败: {e}")
        return True
'''

target_path = os.path.join("src", "wechat_bot.py")
with open(target_path, 'w', encoding='utf-8') as f:
    f.write(file_content)

print(f"V2 修正版已写入: {target_path}")
