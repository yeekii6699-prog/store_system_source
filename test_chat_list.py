"""
简化的会话列表测试脚本
专门用于调试会话列表查找问题
"""

import time
import uiautomation as auto
from loguru import logger

# 添加文件日志
logger.add("chat_list_debug.txt",
           level="DEBUG",
           format="{time:HH:mm:ss} | {message}")

def test_chat_list():
    """测试会话列表查找"""
    print("🔍 测试会话列表查找...")

    # 查找微信窗口
    wechat = auto.WindowControl(searchDepth=1, Name="微信")
    if not wechat.Exists(2):
        print("❌ 未找到微信窗口")
        return

    print("✅ 找到微信窗口")
    window_rect = wechat.BoundingRectangle
    print(f"窗口大小: {window_rect.width()}x{window_rect.height()}")
    logger.info("微信窗口大小: {}x{}", window_rect.width(), window_rect.height())

    # 测试不同的查找路径
    paths = [
        ("路径1: GroupControl.ListControl(会话)",
         lambda: wechat.GroupControl().ListControl(Name="会话", searchDepth=2)),

        ("路径2: GroupControl.ListControl()",
         lambda: wechat.GroupControl().ListControl()),

        ("路径3: 主窗口.ListControl(深度6)",
         lambda: wechat.ListControl(searchDepth=6)),

        ("路径4: 主窗口.ListControl(深度8)",
         lambda: wechat.ListControl(searchDepth=8)),
    ]

    for i, (name, path_func) in enumerate(paths, 1):
        print(f"\n{i}. 测试 {name}")
        logger.info(f"测试 {name}")

        try:
            control = path_func()
            if control and control.Exists(1):
                print(f"   ✅ 找到控件: {control.ControlTypeName}")
                logger.info(f"找到控件: {control.ControlTypeName}")

                # 获取控件信息
                rect = control.BoundingRectangle
                print(f"   位置: ({rect.left}, {rect.top})")
                print(f"   大小: {rect.width()}x{rect.height()}")
                logger.info(f"控件位置: ({rect.left}, {rect.top}) 大小: {rect.width()}x{rect.height()}")

                # 判断是否在左侧（应该在整个窗口的左侧1/3）
                window_rect = wechat.BoundingRectangle
                left_third = window_rect.left + window_rect.width() // 3

                if rect.left < left_third:
                    print(f"   ✅ 在左侧区域 (left={rect.left} < {left_third})")
                    logger.info(f"✅ 在左侧区域")

                    # 获取子项
                    try:
                        children = control.GetChildren()
                        print(f"   子项数量: {len(children)}")
                        logger.info(f"子项数量: {len(children)}")

                        # 显示前3个子项
                        for j, child in enumerate(children[:3], 1):
                            try:
                                child_rect = child.BoundingRectangle
                                child_name = child.Name or "(无名称)"
                                print(f"   子项{j}: {child.ControlTypeName} - {child_name[:30]} 位置({child_rect.left}, {child_rect.top})")
                                logger.info(f"子项{j}: {child.ControlTypeName} - {child_name[:30]} 位置({child_rect.left}, {child_rect.top})")
                            except Exception as e:
                                print(f"   子项{j}: 获取信息失败: {e}")
                                logger.info(f"子项{j}: 获取信息失败: {e}")

                        # 如果看起来是正确的会话列表，直接返回
                        if len(children) > 0:
                            print(f"\n🎯 建议使用路径{i}: {name}")
                            print(f"   这个路径找到了左侧的列表控件，有{len(children)}个子项")
                            logger.info(f"建议使用路径{i}: {name}")
                            return control

                    except Exception as e:
                        print(f"   获取子项失败: {e}")
                        logger.info(f"获取子项失败: {e}")

                else:
                    print(f"   ❌ 不在左侧区域 (left={rect.left} >= {left_third})")
                    logger.info(f"❌ 不在左侧区域")

            else:
                print(f"   ❌ 未找到控件")
                logger.info(f"未找到控件")

        except Exception as e:
            print(f"   ❌ 测试失败: {e}")
            logger.info(f"测试失败: {e}")

    print(f"\n❌ 所有路径都未找到合适的会话列表")
    logger.info("所有路径都未找到合适的会话列表")

if __name__ == "__main__":
    try:
        test_chat_list()
    except Exception as e:
        print(f"测试失败: {e}")
        logger.error(f"测试失败: {e}")

    print(f"\n📋 请查看 chat_list_debug.txt 文件获取详细的调试信息")
    input("按回车键退出...")
