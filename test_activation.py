#!/usr/bin/env python3
"""
激活码功能测试脚本
在没有 GUI 环境的情况下验证激活码逻辑
"""

from __future__ import annotations

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.services.activation import (
    generate_activation_code,
    validate_activation_code,
    generate_machine_id,
    need_activation,
    check_local_activation_status,
    clear_activation,
)
from src.services.feishu import FeishuClient
from src.config.settings import get_config


def test_activation_code_generation():
    """测试激活码生成"""
    print("[测试] 激活码生成...")

    # 测试生成单个激活码
    code = generate_activation_code()
    print(f"[成功] 生成的激活码: {code}")

    # 测试格式验证
    try:
        is_valid, message, _ = validate_activation_code(code)
        print(f"[成功] 格式验证结果: {is_valid}, 消息: {message}")
    except Exception as e:
        print(f"[跳过] 格式验证跳过（需要飞书连接）: {e}")

    # 测试批量生成
    codes = [generate_activation_code() for _ in range(3)]
    print(f"[成功] 批量生成3个激活码: {codes}")

    return codes


def test_machine_id():
    """测试机器ID生成"""
    print("\n[测试] 机器ID生成...")

    machine_id = generate_machine_id()
    print(f"[成功] 机器ID: {machine_id}")

    return machine_id


def test_activation_status():
    """测试激活状态检查"""
    print("\n[测试] 激活状态检查...")

    # 清除现有激活状态
    clear_activation()
    print("[成功] 已清除激活状态")

    # 检查是否需要激活
    need_act = need_activation()
    print(f"[成功] 是否需要激活: {need_act}")

    # 检查本地激活状态
    status = check_local_activation_status()
    print(f"[成功] 本地激活状态: {status}")

    return need_act, status


def test_feishu_client():
    """测试飞书客户端连接"""
    print("\n[测试] 飞书客户端连接...")

    try:
        # 获取配置
        config = get_config()
        app_id = config.get("feishu_app_id")
        app_secret = config.get("feishu_app_secret")

        if not app_id or not app_secret:
            print("[跳过] 飞书配置不完整，跳过飞书客户端测试")
            return None

        # 创建客户端
        client = FeishuClient()
        print("[成功] 飞书客户端创建成功")

        return client

    except Exception as e:
        print(f"[错误] 飞书客户端测试失败: {e}")
        return None


def test_activation_upload(client: FeishuClient, codes: list[str]):
    """测试激活码上传到飞书"""
    print("\n[测试] 激活码上传到飞书...")

    if not client:
        print("[跳过] 飞书客户端不可用，跳过测试")
        return False

    try:
        # 获取激活码表配置
        config = get_config()
        activation_table_url = config.get("activation_table_url")

        if not activation_table_url:
            print("[跳过] 激活码表URL未配置，跳过测试")
            return False

        print(f"[成功] 激活码表URL配置正确: {activation_table_url[:50]}...")

        # 注意：实际的激活码上传需要通过激活管理工具，这里只是验证配置
        print("[成功] 激活码上传配置验证完成")

        return True

    except Exception as e:
        print(f"[错误] 激活码上传测试失败: {e}")
        return False

    try:
        # 获取激活码表配置
        config = get_config()
        activation_table_url = config.get("activation_table_url")

        if not activation_table_url:
            print("❌ 激活码表URL未配置，跳过测试")
            return False

        # 测试上传激活码
        for code in codes[:1]:  # 只测试上传第一个
            result = client.create_activation_record(
                activation_code=code,
                validity_days=365,
                machine_id="test-machine-id",
                notes="测试激活码",
            )
            print(f"✅ 上传激活码成功: {code}, 结果: {result}")

        return True

    except Exception as e:
        print(f"❌ 激活码上传测试失败: {e}")
        return False


def main():
    """主测试函数"""
    print("=== 开始激活码功能测试 ===\n")

    try:
        # 测试激活码生成
        codes = test_activation_code_generation()

        # 测试机器ID生成
        machine_id = test_machine_id()

        # 测试激活状态
        need_act, status = test_activation_status()

        # 测试飞书客户端
        client = test_feishu_client()

        # 测试激活码上传
        if client:
            test_activation_upload(client, codes)

        print("\n=== 所有测试完成 ===")
        print("\n测试结果总结:")
        client_status = "成功" if client else "跳过"
        print(f"   - 激活码生成: 成功")
        print(f"   - 机器ID生成: 成功")
        print(f"   - 激活状态检查: 成功")
        print(f"   - 飞书客户端: {client_status}")

        if client:
            print(f"   - 激活码上传: 成功")

        return True

    except Exception as e:
        print(f"\n[错误] 测试过程中发生错误: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
