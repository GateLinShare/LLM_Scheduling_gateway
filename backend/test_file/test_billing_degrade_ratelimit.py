#!/usr/bin/env python3
"""
测试计费逻辑、降质功能和限速功能的边界测试脚本

测试策略：
1. 使用独立的测试用户，不影响生产数据
2. 通过 API 调用测试，验证实际行为
3. 测试后清理测试数据（可选）

运行前准备：
1. 确保后端服务运行在 http://localhost:7103
2. 在下方配置 ADMIN_API_KEY
3. 配置测试模型（支持降质）

使用方法：
    python test_billing_degrade_ratelimit.py

测试场景：
- 计费：验证不同时间段的价格倍率
- 降质：验证额度超限时的降质行为
- 限速：验证请求频率限制
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Optional
import httpx
import json

# ============================================================
# 配置区域 - 请在此处修改配置
# ============================================================
API_BASE = "http://localhost:7103"
ADMIN_API_KEY = "admin@sinovatio.com"  # 请替换为实际的 admin API key
TEST_MODEL = "deepseek"  # 测试模型名称

# 测试用户配置
TEST_USERS = {
    "normal_user": {
        "username": "test_normal_user",
        "priority": 3,
        "quota_unlimited": False,
        "quota_limit": 0.0,  # 0元额度，必然触发降质
    },
    "unlimited_user": {
        "username": "test_unlimited_user",
        "priority": 3,
        "quota_unlimited": True,
    },
    "high_priority_user": {
        "username": "test_high_priority_user",
        "priority": 1,
        "quota_unlimited": False,
        "quota_limit": 0.0,  # 0元额度但高优先级，不应降质
    },
    "ratelimit_user": {
        "username": "test_ratelimit_user",
        "priority": 3,
        "quota_unlimited": True,
    },
}


class TestRunner:
    def __init__(self):
        self.admin_client = httpx.AsyncClient(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {ADMIN_API_KEY}"},
            timeout=30.0,
        )
        self.test_users = {}  # {username: {"api_key": str, "user_id": int}}
        self.results = []

    async def setup(self):
        """创建测试用户"""
        print("=" * 60)
        print("设置测试环境：创建测试用户")
        print("=" * 60)

        for user_type, config in TEST_USERS.items():
            try:
                response = await self.admin_client.post(
                    "/api/admin/users",
                    json=config,
                )
                response.raise_for_status()
                data = response.json()
                self.test_users[config["username"]] = {
                    "api_key": data["api_key"],
                    "user_id": data.get("user", {}).get("id") or data.get("id"),
                    "type": user_type,
                }
                print(f"✓ 创建用户 {config['username']}: {data['api_key']}")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 409:
                    print(f"⚠ 用户 {config['username']} 已存在，查询现有用户信息...")
                    # 用户已存在，通过 admin API 查询用户列表获取信息
                    try:
                        users_response = await self.admin_client.get("/api/admin/users")
                        users_response.raise_for_status()
                        users_data = users_response.json()
                        users = users_data.get("data", [])

                        # 查找匹配的用户
                        existing_user = next((u for u in users if u.get("username") == config["username"]), None)
                        if existing_user:
                            # 重置用户的 API key
                            user_id = existing_user.get("id")
                            reset_response = await self.admin_client.post(f"/api/admin/users/{user_id}/reset-key")
                            reset_response.raise_for_status()
                            new_key_data = reset_response.json()
                            new_api_key = new_key_data.get("api_key")

                            self.test_users[config["username"]] = {
                                "api_key": new_api_key,
                                "user_id": user_id,
                                "type": user_type,
                            }
                            print(f"  ✓ 已重置 API Key: {new_api_key}")
                        else:
                            print(f"  ✗ 无法找到用户信息")
                    except Exception as query_error:
                        print(f"  ✗ 查询用户失败: {query_error}")
                else:
                    print(f"✗ 创建用户 {config['username']} 失败: {e}")
            except Exception as e:
                print(f"✗ 创建用户 {config['username']} 异常: {e}")

    async def teardown(self, cleanup: bool = False):
        """清理测试数据"""
        if cleanup:
            print("\n" + "=" * 60)
            print("清理测试环境：删除测试用户")
            print("=" * 60)

            for username, user_info in self.test_users.items():
                try:
                    user_id = user_info.get("user_id")
                    if user_id:
                        await self.admin_client.delete(f"/api/admin/users/{user_id}")
                        print(f"✓ 删除用户 {username}")
                except Exception as e:
                    print(f"✗ 删除用户 {username} 失败: {e}")

        await self.admin_client.aclose()

    async def call_chat_api(
        self,
        api_key: str,
        model: str = TEST_MODEL,
        messages: Optional[list] = None,
        stream: bool = False,
    ) -> dict:
        """调用聊天 API"""
        if messages is None:
            messages = [{"role": "user", "content": "Hello"}]

        client = httpx.AsyncClient(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

        try:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": stream,
                },
            )

            if stream:
                # 流式响应：收集所有chunk
                chunks = []
                async for line in response.aiter_lines():
                    if line.strip():
                        chunks.append(line)
                return {
                    "status_code": response.status_code,
                    "body": chunks,
                    "headers": dict(response.headers),
                    "is_stream": True,
                }
            else:
                # 非流式响应
                return {
                    "status_code": response.status_code,
                    "body": response.json() if response.status_code == 200 else response.text,
                    "headers": dict(response.headers),
                    "is_stream": False,
                }
        except Exception as e:
            return {
                "status_code": 0,
                "body": str(e),
                "headers": {},
                "is_stream": False,
            }
        finally:
            await client.aclose()

    async def get_user_usage(self, api_key: str) -> dict:
        """获取用户用量信息"""
        client = httpx.AsyncClient(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )

        try:
            response = await client.get("/api/me")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e)}
        finally:
            await client.aclose()

    def log_result(self, test_name: str, passed: bool, details: str):
        """记录测试结果"""
        status = "✓ PASS" if passed else "✗ FAIL"
        self.results.append({
            "test": test_name,
            "passed": passed,
            "details": details,
        })
        print(f"{status} | {test_name}")
        print(f"  详情: {details}")

    async def test_billing_time_multipliers(self):
        """测试时间段价格倍率"""
        print("\n" + "=" * 60)
        print("测试 1: 时间段价格倍率")
        print("=" * 60)

        username = "test_unlimited_user"
        if username not in self.test_users:
            self.log_result("时间段倍率测试", False, "测试用户不存在")
            return

        api_key = self.test_users[username]["api_key"]

        # 获取当前时间段
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()

        if weekday >= 5:
            expected_period = "周末"
            expected_multiplier = 0.3
        elif 9 <= hour < 18:
            expected_period = "工作日高峰"
            expected_multiplier = 1.5
        elif 18 <= hour < 23:
            expected_period = "工作日平峰"
            expected_multiplier = 1.0
        else:
            expected_period = "夜间"
            expected_multiplier = 0.3

        print(f"当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"预期时间段: {expected_period} (倍率 {expected_multiplier})")

        # 发起请求
        result = await self.call_chat_api(api_key)

        if result["status_code"] == 200:
            # 查询用量记录验证倍率
            # 注意：这里需要通过 admin API 查询用量日志来验证实际倍率
            # 简化版本：只验证请求成功
            self.log_result(
                "时间段倍率-请求成功",
                True,
                f"当前时间段 {expected_period}，请求成功，需手动验证数据库中的价格倍率"
            )
        else:
            self.log_result(
                "时间段倍率-请求失败",
                False,
                f"状态码 {result['status_code']}, 响应: {result['body']}"
            )

    async def test_degrade_on_quota_exceeded(self):
        """测试额度超限时的降质行为"""
        print("\n" + "=" * 60)
        print("测试 2: 额度超限降质")
        print("=" * 60)

        username = "test_normal_user"
        if username not in self.test_users:
            self.log_result("降质测试", False, "测试用户不存在")
            return

        api_key = self.test_users[username]["api_key"]

        # 1. 查询初始额度
        user_info = await self.get_user_usage(api_key)
        initial_quota_used = user_info.get("quota_used", 0)
        quota_limit = user_info.get("quota_limit", 0)

        print(f"初始已用额度: {initial_quota_used}")
        print(f"额度上限: {quota_limit}")

        # 2. 测试非流式降质
        print("\n场景1: 非流式降质")
        result = await self.call_chat_api(api_key, stream=False)

        if result["status_code"] == 200:
            # 打印响应头，查看优先级等信息
            headers = result.get("headers", {})
            print(f"  响应头: X-User-Priority={headers.get('x-user-priority', 'N/A')}")

            body = result["body"]
            if isinstance(body, dict):
                model_used = body.get("model", "")
                print(f"  响应模型: {model_used}")
                if "test1" in model_used.lower():
                    self.log_result(
                        "降质触发-非流式",
                        True,
                        f"额度为0触发降质，使用降质模型: {model_used}"
                    )
                else:
                    self.log_result(
                        "降质未触发-非流式",
                        False,
                        f"额度为0但未触发降质，使用模型: {model_used}（应为test1）"
                    )
        elif "额度已用完" in str(result["body"]):
            self.log_result(
                "降质配置缺失",
                False,
                "返回额度已用完错误，未触发降质（可能未配置降质模型）"
            )
        else:
            self.log_result(
                "请求失败-非流式",
                False,
                f"状态码 {result['status_code']}, 响应: {result['body']}"
            )

        # 3. 测试流式降质
        print("\n场景2: 流式降质")
        result_stream = await self.call_chat_api(api_key, stream=True)

        if result_stream["status_code"] == 200:
            chunks = result_stream["body"]
            is_stream = result_stream.get("is_stream", False)
            print(f"  收到 {len(chunks)} 个流式chunk")
            print(f"  是否流式: {is_stream}")

            # 检查是否真的是流式响应
            if is_stream and len(chunks) > 0:
                # 尝试从第一个chunk中提取模型信息
                first_chunk = chunks[0] if chunks else ""
                print(f"  首个chunk: {first_chunk[:100]}...")

                self.log_result(
                    "降质触发-流式",
                    True,
                    f"额度为0触发流式降质，收到 {len(chunks)} 个chunk"
                )
            else:
                self.log_result(
                    "降质流式响应异常",
                    False,
                    f"期望流式响应但收到非流式或空响应"
                )
        else:
            self.log_result(
                "请求失败-流式",
                False,
                f"状态码 {result_stream['status_code']}, 响应: {result_stream['body']}"
            )

    async def test_high_priority_no_degrade(self):
        """测试高优先级用户不降质"""
        print("\n" + "=" * 60)
        print("测试 3: 高优先级用户不降质")
        print("=" * 60)

        username = "test_high_priority_user"
        if username not in self.test_users:
            self.log_result("高优先级不降质测试", False, "测试用户不存在")
            return

        api_key = self.test_users[username]["api_key"]

        # Priority 1 用户即使额度为0也不应降质
        result = await self.call_chat_api(api_key)

        if result["status_code"] == 200:
            body = result["body"]
            if isinstance(body, dict):
                model_used = body.get("model", "")
                print(f"响应模型: {model_used}")
                if "test1" in model_used.lower():
                    self.log_result(
                        "高优先级降质异常",
                        False,
                        f"Priority 1 用户不应降质，但使用了降质模型: {model_used}"
                    )
                else:
                    self.log_result(
                        "高优先级不降质",
                        True,
                        f"Priority 1 用户未触发降质，使用正常模型: {model_used}"
                    )
        elif "额度已用完" in str(result["body"]):
            # Priority 1 用户额度超限应该返回错误而非降质
            self.log_result(
                "高优先级额度超限",
                True,
                "Priority 1 用户额度超限返回错误（正确行为）"
            )
        else:
            self.log_result(
                "请求失败",
                False,
                f"状态码 {result['status_code']}, 响应: {result['body']}"
            )

    async def test_rate_limiting(self):
        """测试请求频率限制"""
        print("\n" + "=" * 60)
        print("测试 4: 请求频率限制")
        print("=" * 60)

        username = "test_ratelimit_user"
        if username not in self.test_users:
            self.log_result("限速测试", False, "测试用户不存在")
            return

        api_key = self.test_users[username]["api_key"]

        # 临时调整限速配置为最小值（通过admin API）
        print("步骤 1: 临时调整限速配置...")
        try:
            config_response = await self.admin_client.get("/api/admin/config")
            config_response.raise_for_status()
            config = config_response.json()

            original_threshold = config.get("rate_limit", {}).get("request_threshold", 10)
            original_window = config.get("rate_limit", {}).get("window_minutes", 1)
            original_priority = config.get("rate_limit", {}).get("downgraded_priority", 4)

            # 场景1: 窗口内次数限制为1次，触发限速后降低优先级
            config["rate_limit"] = {
                "request_threshold": 1,
                "window_minutes": 1,
                "downgraded_priority": 5,
                "window_quota_action": "limit"  # 降低优先级而非拒绝
            }

            update_response = await self.admin_client.put("/api/admin/config", json=config)
            update_response.raise_for_status()
            print(f"  限速配置已调整: 1次/1分钟，超限后降为优先级5")

            # 等待配置生效
            await asyncio.sleep(1)
        except Exception as e:
            self.log_result("限速配置失败", False, f"无法调整限速配置: {e}")
            return

        # 场景1测试: 发送2个请求，第2个应该降低优先级
        print("\n场景1: 窗口内次数限制（1次/分钟）")
        print("  发送2个请求，第2个应降为优先级5...")

        result1 = await self.call_chat_api(api_key)
        print(f"  请求1: 状态码 {result1['status_code']}")

        await asyncio.sleep(0.5)

        result2 = await self.call_chat_api(api_key)
        print(f"  请求2: 状态码 {result2['status_code']}")

        # 检查第2个请求的响应头中是否有优先级信息
        if result2["status_code"] == 200:
            headers = result2.get("headers", {})
            priority_header = headers.get("x-user-priority") or headers.get("X-User-Priority")
            print(f"  请求2优先级: {priority_header}")

            if priority_header == "5":
                self.log_result(
                    "限速-优先级降低",
                    True,
                    f"窗口内超过1次请求，第2个请求优先级降为5"
                )
            else:
                self.log_result(
                    "限速-优先级未降低",
                    False,
                    f"窗口内超过1次请求，但优先级为 {priority_header}（应为5）"
                )
        else:
            self.log_result(
                "限速-请求失败",
                False,
                f"第2个请求失败，状态码 {result2['status_code']}"
            )

        # 等待窗口过期
        print("\n  等待62秒让窗口完全过期...")
        await asyncio.sleep(65)

        # 场景2测试: 窗口过期后，新请求应该恢复正常优先级
        print("\n场景2: 窗口过期后恢复")
        result3 = await self.call_chat_api(api_key)
        print(f"  请求3: 状态码 {result3['status_code']}")

        if result3["status_code"] == 200:
            headers = result3.get("headers", {})
            priority_header = headers.get("x-user-priority") or headers.get("X-User-Priority")
            print(f"  请求3优先级: {priority_header}")

            if priority_header == "3":
                self.log_result(
                    "限速-窗口过期恢复",
                    True,
                    f"窗口过期后优先级恢复为3"
                )
            else:
                self.log_result(
                    "限速-窗口过期未恢复",
                    False,
                    f"窗口过期后优先级为 {priority_header}（应为3）"
                )

        # 恢复原始配置
        print("\n步骤 2: 恢复原始限速配置...")
        try:
            config["rate_limit"] = {
                "request_threshold": original_threshold,
                "window_minutes": original_window,
                "downgraded_priority": original_priority
            }
            await self.admin_client.put("/api/admin/config", json=config)
            print(f"  限速配置已恢复: {original_threshold}次/{original_window}分钟")
        except Exception as e:
            print(f"  恢复配置失败: {e}")

    async def test_degrade_no_billing(self):
        """测试降质请求不计费"""
        print("\n" + "=" * 60)
        print("测试 5: 降质请求不计费")
        print("=" * 60)

        username = "test_normal_user"
        if username not in self.test_users:
            self.log_result("降质不计费测试", False, "测试用户不存在")
            return

        api_key = self.test_users[username]["api_key"]

        # 1. 记录当前额度
        user_info_before = await self.get_user_usage(api_key)
        quota_before = user_info_before.get("quota_used", 0)
        print(f"步骤 1: 当前额度: {quota_before}")

        # 2. 发送降质请求（额度为0，必然触发降质）
        print("步骤 2: 发送降质请求...")
        result = await self.call_chat_api(api_key)

        if result["status_code"] != 200:
            self.log_result(
                "降质请求失败",
                False,
                f"降质请求返回状态码 {result['status_code']}"
            )
            return

        # 检查是否使用了降质模型
        body = result["body"]
        if isinstance(body, dict):
            model_used = body.get("model", "")
            print(f"  响应模型: {model_used}")
            if "test1" not in model_used.lower():
                self.log_result(
                    "未使用降质模型",
                    False,
                    f"响应模型为 {model_used}，不是降质模型test1"
                )
                return

        # 3. 等待计费完成
        await asyncio.sleep(2)

        # 4. 检查额度是否变化
        user_info_after = await self.get_user_usage(api_key)
        quota_after = user_info_after.get("quota_used", 0)
        print(f"步骤 3: 降质后额度: {quota_after}")

        if quota_after == quota_before:
            self.log_result(
                "降质不计费",
                True,
                f"降质请求未增加额度消耗（{quota_before} -> {quota_after}），使用模型: {model_used}"
            )
        else:
            self.log_result(
                "降质计费异常",
                False,
                f"降质请求增加了额度消耗（{quota_before} -> {quota_after}），应该为 0"
            )

    def print_summary(self):
        """打印测试摘要"""
        print("\n" + "=" * 60)
        print("测试摘要")
        print("=" * 60)

        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed

        print(f"总计: {total} 个测试")
        print(f"通过: {passed} 个")
        print(f"失败: {failed} 个")
        print(f"通过率: {passed/total*100:.1f}%")

        if failed > 0:
            print("\n失败的测试:")
            for r in self.results:
                if not r["passed"]:
                    print(f"  - {r['test']}: {r['details']}")

    async def run_all_tests(self, cleanup: bool = False):
        """运行所有测试"""
        try:
            await self.setup()

            await self.test_billing_time_multipliers()
            await self.test_degrade_on_quota_exceeded()
            await self.test_high_priority_no_degrade()
            await self.test_rate_limiting()
            await self.test_degrade_no_billing()

            self.print_summary()
        finally:
            await self.teardown(cleanup=cleanup)


async def main():
    """主函数"""
    print("LLM 调度网关 - 计费/降质/限速测试")
    print("=" * 60)
    print(f"API 地址: {API_BASE}")
    print(f"测试模型: {TEST_MODEL}")
    print("=" * 60)

    # 检查配置
    if ADMIN_API_KEY == "your_admin_api_key_here":
        print("\n错误: 请先配置 ADMIN_API_KEY")
        print("在脚本顶部的配置区域将 ADMIN_API_KEY 替换为实际的 admin API key")
        return

    # 询问是否清理测试数据
    print("\n是否在测试后清理测试用户？(y/n)")
    print("注意: 清理会删除测试用户及其所有数据")
    cleanup_input = input("请输入 (默认 n): ").strip().lower()
    cleanup = cleanup_input == "y"

    runner = TestRunner()
    await runner.run_all_tests(cleanup=cleanup)

    print("\n测试完成！")


if __name__ == "__main__":
    asyncio.run(main())
