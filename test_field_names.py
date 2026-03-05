#!/usr/bin/env python3
"""
测试字段名的正确编码
"""

from __future__ import annotations

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.services.feishu import FeishuClient


def main():
    """测试创建记录"""
    print("=== 测试创建激活码记录 ===\n")

    activation_url = "https://my.feishu.cn/wiki/R8PDwJPxXiezYEkdop7cn4QInEc?table=tblWYoLIpX3FJBQi&view=vewFXKdZxl"

    try:
        client = FeishuClient()

        # 测试创建最简单的记录
        fields = {
            "id": "test123",  # 尝试 id 字段
        }

        print(f"尝试创建记录，字段: {fields}")
        record_id = client.create_record(fields)
        print(f"创建成功: {record_id}")

    except Exception as e:
        print(f"创建失败: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
