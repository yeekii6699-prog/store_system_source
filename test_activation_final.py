#!/usr/bin/env python3
"""
使用正确字段名的激活测试工具
"""

from __future__ import annotations

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.services.activation import activate_code


def main():
    """测试激活功能"""
    print("=== 测试激活码功能 ===\n")

    # 使用之前生成的激活码
    test_code = "QVJO-30ST-OQPF-45IG"

    try:
        result = activate_code(test_code)
        print(f"激活成功!")
        print(f"结果: {result}")
    except Exception as e:
        print(f"激活失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
