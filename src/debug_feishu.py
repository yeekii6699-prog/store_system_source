import requests
import json

# ================= 诊断配置区 =================
# 1. 请手动填入你的 App ID 和 Secret
APP_ID = "cli_a9b086cec3f85bd8"  
APP_SECRET = "eIAeNYRw3tHiLgB6mb0gegbaYrZJXzVe"

# 2. 请手动填入你浏览器地址栏里的那个 Wiki Token (就是 Uxtv... 那个)
APP_TOKEN = "UxtvwaKdfiJC36kXs0gcS13bnwb" 

# 3. 请手动填入你【预约流水表】的 Table ID (就是 tbl... 那个)
TABLE_ID = "tblHwp8cJOWRL0Oz" 
# ============================================

def debug_feishu():
    print("----------- 1. 开始获取 Token -----------")
    url_token = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url_token, json={"app_id": APP_ID, "app_secret": APP_SECRET})
    
    if resp.status_code != 200:
        print(f"❌ 获取 Token 失败: {resp.text}")
        return
    
    token = resp.json().get("tenant_access_token")
    print(f"✅ 获取 Token 成功: {token[:10]}...")
    
    print("\n----------- 2. 尝试列出表格所有字段 -----------")
    # 我们不筛选，直接拿前 10 条数据，看看有哪些字段
    url_list = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records?page_size=10"
    headers = {"Authorization": f"Bearer {token}"}
    
    resp = requests.get(url_list, headers=headers)
    
    if resp.status_code == 200:
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        print(f"✅ 连接表格成功！共获取到 {len(items)} 条数据。")
        
        if items:
            print("\n🔍 侦测到第一条数据的字段如下（请仔细核对名称）：")
            fields = items[0].get("fields", {})
            for key, value in fields.items():
                print(f"   👉 字段名: [{key}]  |  值: {value}")
                
            print("\n----------------诊断结论----------------")
            if "处理状态" in fields:
                print("✅ 恭喜：找到了【处理状态】字段！")
            else:
                print("❌ 警告：没找到【处理状态】字段！代码里筛选肯定会报错！")
                print("   请检查飞书表格里，这列是不是叫'状态'？'State'？还是有空格？")
        else:
            print("⚠️ 表格是空的，建议先手动随便填一条数据进去再测试。")
            
    else:
        print(f"❌ 连接表格失败！错误代码: {resp.status_code}")
        print(f"❌ 错误详情: {resp.text}")
        print("\n💡 可能原因：")
        print("1. TABLE_ID 填错了（请去浏览器地址栏再看一眼）。")
        print("2. APP_TOKEN (Wiki ID) 不对，可能需要换成 bascn 开头的 Base ID。")
        print("3. 飞书后台权限没开（多维表格:阅读）。")

if __name__ == "__main__":
    debug_feishu()