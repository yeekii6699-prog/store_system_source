# 网络配置指南

## 概述

本系统支持在各种网络环境下运行，包括VPN、代理等。系统会自动检测网络环境并调整配置。

## 网络配置选项

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `NETWORK_PROXY` | 空 | 手动配置的代理服务器URL |
| `NETWORK_VERIFY_SSL` | `1` | 是否验证SSL证书 (1=启用, 0=禁用) |
| `NETWORK_TIMEOUT` | `15` | 网络请求超时时间(秒) |
| `NETWORK_USE_SYSTEM_PROXY` | `0` | 是否使用系统代理 (1=启用, 0=禁用) |

### 配置文件 (config.ini)

```ini
[DEFAULT]
NETWORK_PROXY = http://proxy.example.com:8080
NETWORK_VERIFY_SSL = 1
NETWORK_TIMEOUT = 15
NETWORK_USE_SYSTEM_PROXY = 0
```

## 常见网络环境配置

### 1. 正常网络环境
无需额外配置，系统使用默认设置。

### 2. 使用VPN
系统会自动检测VPN环境，如果遇到SSL错误，可以：

- 关闭VPN后重新启动程序
- 或者在配置中设置：
  ```
  NETWORK_VERIFY_SSL = 0  # 禁用SSL验证
  NETWORK_TIMEOUT = 30    # 增加超时时间
  ```

### 3. 使用代理服务器
#### 手动配置代理
```
NETWORK_PROXY = http://proxy.example.com:8080
# 或带认证的代理
NETWORK_PROXY = http://username:password@proxy.example.com:8080
```

#### 使用系统代理
```
NETWORK_USE_SYSTEM_PROXY = 1
```

### 4. 企业网络环境
企业网络可能有防火墙或SSL证书问题：

```ini
NETWORK_VERIFY_SSL = 0    # 如果有证书验证问题
NETWORK_TIMEOUT = 30      # 增加超时时间
NETWORK_PROXY = http://corporate-proxy:8080  # 配置企业代理
```

## 故障排除

### SSL错误
```
SSLError: EOF occurred in violation of protocol
```

**解决方案：**
1. 关闭VPN或代理
2. 设置 `NETWORK_VERIFY_SSL = 0`
3. 配置正确的代理设置

### 连接超时
```
TimeoutError: Request timed out
```

**解决方案：**
1. 增加 `NETWORK_TIMEOUT` 值
2. 检查网络连接
3. 配置代理服务器

### 代理认证失败
```
ProxyError: 407 Proxy Authentication Required
```

**解决方案：**
1. 检查代理URL是否包含用户名密码
2. 确认代理服务器认证信息正确

## 自动检测功能

系统启动时会自动检测：

- ✅ VPN/代理环境
- ✅ 系统代理设置
- ✅ SSL证书配置
- ✅ 网络连接状态

检测到的信息会在日志中显示：

```
🌐 检测到VPN/代理环境: {...}
🔌 检测到系统代理: {...}
🔍 测试飞书服务器连接...
✅ 网络连接测试成功
```

## 最佳实践

1. **开发环境**：使用默认配置，确保网络连接正常
2. **生产环境**：根据实际网络环境配置相应的代理和SSL设置
3. **企业环境**：联系IT部门获取正确的代理服务器信息
4. **海外访问**：考虑配置合适的代理服务器或VPN

## 安全注意事项

- 禁用SSL验证 (`NETWORK_VERIFY_SSL = 0`) 会降低安全性，仅建议在可信网络环境下使用
- 代理配置中的密码会以明文存储，注意配置文件安全
- 企业环境下建议使用企业提供的代理服务器

## 命令行测试

可以使用以下命令测试网络连接：

```bash
# 测试基本连接
curl -I https://open.feishu.cn

# 使用代理测试
curl -I --proxy http://proxy.example.com:8080 https://open.feishu.cn

# 禁用SSL验证测试
curl -k -I https://open.feishu.cn
```