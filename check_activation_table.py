#!/usr/bin/env python3
"""
检查激活码表的字段结构
"""

from __future__ import annotations

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.services.feishu import FeishuClient


def main():
    """检查激活码表的字段"""
    print("=== 检查激活码表字段结构 ===\n")

    # 你的激活码表URL
    activation_url = "https://my.feishu.cn/wiki/R8PDwJPxXiezYEkdop7cn4QInEc?table=tblWYoLIpX3FJBQi&view=vewFXKdZxl"

    print(f"激活码表URL: {activation_url}\n")

    try:
        client = FeishuClient()

        # 获取字段列表
        fields = client.list_fields(activation_url)

        print("字段列表:")
        for i, field in enumerate(fields, 1):
            field_name = field.get("field_name", "")
            field_type = field.get("type", "")
            print(f"{i}. {field_name} -> {field_type}")

        print(f"\n总计 {len(fields)} 个字段")

        # 检查是否有激活码相关字段
        field_names = [f.get("field_name", "") for f in fields]

        required_fields = [
            "激活码",
            "状态",
            "时长（天）",
            "机器ID",
            "激活时间",
            "到期时间",
            "备注",
        ]
        print(f"\n字段匹配检查:")
        for req_field in required_fields:
            if req_field in field_names:
                print(f"✅ {req_field}")
            else:
                print(f"❌ {req_field} - 未找到")
                # 查找相似字段名
                similar = [
                    f
                    for f in field_names
                    if req_field.replace("（", "").replace("）", "").replace("天", "")
                    in f
                ]
                if similar:
                    print(f"   相似字段: {similar}")

    except Exception as e:
        print(f"错误: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
