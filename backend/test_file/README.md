# 测试脚本使用说明

## 概述

`test_billing_degrade_ratelimit.py` 是一个边界测试脚本，用于测试 LLM 调度网关的计费逻辑、降质功能和限速功能。

## 测试策略

该脚本通过以下方式实现**不影响主逻辑的边界测试**：

1. **独立测试用户**：创建专用的测试用户（用户名带 `test_` 前缀），与生产用户隔离
2. **API 层测试**：通过 HTTP API 调用测试，验证实际运行行为，不修改代码
3. **可选清理**：测试完成后可选择删除测试用户和数据，保持环境整洁
4. **边界场景覆盖**：针对临界值、异常情况进行测试

## 测试场景

### 1. 时间段价格倍率测试
- **目的**：验证不同时间段的价格倍率是否正确应用
- **方法**：根据当前时间判断应处于哪个时间段，发送请求后检查计费
- **边界**：测试时间段边界（9:00, 18:00, 23:00）

### 2. 额度超限降质测试
- **目的**：验证用户额度超限时是否正确触发降质
- **方法**：使用低额度用户持续发送请求，直到触发降质
- **边界**：额度刚好达到上限时的行为

### 3. 高优先级用户不降质测试
- **目的**：验证 Priority 1 用户即使额度超限也不降质
- **方法**：使用 Priority 1 + 低额度用户发送请求
- **边界**：高优先级用户的特殊处理逻辑

### 4. 请求频率限制测试
- **目的**：验证限速机制是否生效
- **方法**：快速连续发送多个请求，检查是否返回 429 状态码
- **边界**：请求频率刚好达到阈值时的行为

### 5. 降质请求不计费测试（关键）
- **目的**：验证降质请求不触发计费、不消耗 token 额度
- **方法**：触发降质后记录额度，发送降质请求，检查额度是否变化
- **边界**：降质请求的计费逻辑完全独立

## 使用方法

### 1. 准备工作

```bash
# 安装依赖
pip install httpx

# 确保后端服务运行
cd /home/tsn/github_code/LLM_Scheduling/backend
./start.sh
```

### 2. 配置脚本

编辑 `test_billing_degrade_ratelimit.py`，修改以下配置：

```python
# 必须配置
ADMIN_API_KEY = "your_admin_api_key_here"  # 替换为实际的 admin API key

# 可选配置
API_BASE = "http://localhost:7103"  # 后端地址
TEST_MODEL = "test-model"  # 测试模型名称（需要在系统中配置）
```

### 3. 配置测试模型

在系统中配置一个测试模型，包含降质设置：

```json
{
  "test-model": {
    "queue_name": "test-queue",
    "api_url": "http://your-llm-api.com",
    "model_name": "gpt-3.5-turbo",
    "api_key": "your-api-key",
    "price": {
      "input_per_1k": 0.01,
      "output_per_1k": 0.02,
      "currency": "CNY"
    },
    "price_multipliers": {
      "weekday_peak": 1.5,
      "weekday_flat": 1.0,
      "night": 0.3,
      "weekend": 0.3
    },
    "degrade": {
      "enabled": true,
      "api_url": "http://your-fallback-api.com",
      "model_name": "gpt-3.5-turbo-degrade",
      "api_key": "your-fallback-api-key"
    }
  }
}
```

### 4. 运行测试

```bash
cd /home/tsn/github_code/LLM_Scheduling/backend/test_file
python3 test_billing_degrade_ratelimit.py
```

### 5. 查看结果

脚本会输出详细的测试过程和结果：

```
LLM 调度网关 - 计费/降质/限速测试
============================================================
API 地址: http://localhost:7103
测试模型: test-model
============================================================

设置测试环境：创建测试用户
============================================================
✓ 创建用户 test_normal_user: sk-xxx
✓ 创建用户 test_unlimited_user: sk-yyy
...

测试 1: 时间段价格倍率
============================================================
当前时间: 2026-05-21 14:30:00
预期时间段: 工作日高峰 (倍率 1.5)
✓ PASS | 时间段倍率-请求成功
  详情: 当前时间段 工作日高峰，请求成功，需手动验证数据库中的价格倍率

...

测试摘要
============================================================
总计: 5 个测试
通过: 4 个
失败: 1 个
通过率: 80.0%
```

## 测试用户说明

脚本会创建以下测试用户：

| 用户名 | 优先级 | 额度限制 | 用途 |
|--------|--------|----------|------|
| test_normal_user | 3 | 1.0 元 | 测试降质和计费 |
| test_unlimited_user | 3 | 无限制 | 测试时间段倍率 |
| test_high_priority_user | 1 | 0.1 元 | 测试高优先级不降质 |
| test_ratelimit_user | 3 | 无限制 | 测试限速 |

## 清理测试数据

测试完成后，脚本会询问是否清理测试用户：

```
是否在测试后清理测试用户？(y/n)
注意: 清理会删除测试用户及其所有数据
请输入 (默认 n): y
```

- 输入 `y`：删除所有测试用户及其用量记录
- 输入 `n` 或直接回车：保留测试用户，方便后续调试

## 手动验证

某些测试需要手动验证数据库数据：

### 验证时间段倍率

```sql
-- 查询最近的用量记录
SELECT 
    created_at,
    username,
    model_name,
    prompt_tokens,
    completion_tokens,
    input_price,
    output_price,
    total_price
FROM gateway_usage_logs
WHERE username LIKE 'test_%'
ORDER BY created_at DESC
LIMIT 10;

-- 计算实际倍率
-- 实际倍率 = total_price / (prompt_tokens/1000 * input_per_1k + completion_tokens/1000 * output_per_1k)
```

### 验证降质不计费

```sql
-- 查询降质请求的用量记录
SELECT 
    created_at,
    username,
    request_id,
    model_name,
    upstream_model_name,
    total_price
FROM gateway_usage_logs
WHERE username = 'test_normal_user'
  AND request_id LIKE 'degrade:%'
ORDER BY created_at DESC;

-- 降质请求应该没有用量记录，或者 total_price = 0
```

## 注意事项

1. **不影响生产**：测试用户与生产用户完全隔离，使用独立的用户名前缀
2. **可重复运行**：脚本会检查用户是否已存在，避免重复创建
3. **异步执行**：使用 asyncio 提高测试效率
4. **超时保护**：所有 HTTP 请求都设置了 30 秒超时
5. **错误处理**：捕获并记录所有异常，不会中断测试流程

## 扩展测试

可以根据需要添加更多测试场景：

```python
async def test_custom_scenario(self):
    """自定义测试场景"""
    print("\n" + "=" * 60)
    print("测试 X: 自定义场景")
    print("=" * 60)
    
    # 测试逻辑
    # ...
    
    self.log_result("测试名称", passed, "详细信息")
```

然后在 `run_all_tests` 中调用：

```python
async def run_all_tests(self, cleanup: bool = False):
    try:
        await self.setup()
        
        await self.test_billing_time_multipliers()
        await self.test_degrade_on_quota_exceeded()
        await self.test_high_priority_no_degrade()
        await self.test_rate_limiting()
        await self.test_degrade_no_billing()
        await self.test_custom_scenario()  # 添加自定义测试
        
        self.print_summary()
    finally:
        await self.teardown(cleanup=cleanup)
```

## 故障排查

### 问题：测试用户创建失败

**原因**：ADMIN_API_KEY 无效或权限不足

**解决**：
1. 检查 ADMIN_API_KEY 是否正确
2. 确认该 API Key 对应的用户角色为 admin
3. 查看后端日志确认错误原因

### 问题：降质未触发

**原因**：
1. 测试模型未配置降质
2. 用户额度设置过高
3. 模型价格过低，难以触发额度超限

**解决**：
1. 检查模型配置中的 `degrade.enabled` 是否为 true
2. 降低测试用户的 `quota_limit`（如 0.1 元）
3. 提高模型价格或发送更多请求

### 问题：限速未触发

**原因**：限速阈值设置过高或窗口时间过长

**解决**：
1. 检查系统配置中的 `rate_limit.request_threshold`
2. 检查 `rate_limit.window_minutes`
3. 增加测试请求数量

## 总结

该测试脚本通过以下方式实现了**不影响主逻辑的边界测试**：

✅ 使用独立测试用户，与生产数据隔离  
✅ 通过 API 调用测试，不修改代码  
✅ 覆盖关键边界场景（额度临界、时间边界、优先级特殊处理）  
✅ 可选清理测试数据，保持环境整洁  
✅ 详细的测试报告和手动验证指南  

运行测试后，可以验证计费、降质、限速功能是否按预期工作，发现潜在的边界问题。
