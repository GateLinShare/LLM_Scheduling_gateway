#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Gateway 测试脚本
包含所有API接口的测试用例
"""

import requests
import base64
import json
import sys

# ==================== 配置区域 ====================
# Gateway 服务地址
GATEWAY_URL = "http://10.45.155.205:7102"

# OCR 测试图片路径
OCR_IMAGE_PATH = "/data01/tsn/code_test/LLM_Scheduling/backend/test_file/image.png"

# 测试模型名称 (对应 config.py 中的 MODELS 配置)
MODEL_NAME = "testname-coder"

# API Key (如需要)
API_KEY = "sk-ALTbgl6ut981w"

# 超时设置
TIMEOUT = 60
# ================================================


# ================== 测试1: OCR文件上传 ==================


def test_ocr_file_upload():
    """测试OCR文件上传方式"""
    print("=" * 50)
    print("1. 测试OCR文件上传方式")
    print("=" * 50)
    url = f"{GATEWAY_URL}/v1/ocr"
    
    try:
        with open(OCR_IMAGE_PATH, 'rb') as f:
            file_dict = {'image_file': (OCR_IMAGE_PATH, f, 'image/png')}
            response = requests.post(url, files=file_dict, timeout=TIMEOUT)
        
        print(f"状态码: {response.status_code}")
        print(f"响应长度: {len(response.text)}")
        print(f"响应内容: {response.text[:500]}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False


# ================== 测试2: OCR Base64编码 ==================


def test_ocr_base64():
    """测试OCR Base64编码方式"""
    print("\n" + "=" * 50)
    print("2. 测试OCR Base64编码方式")
    print("=" * 50)
    url = f"{GATEWAY_URL}/v1/ocr"
    
    try:
        with open(OCR_IMAGE_PATH, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')
        
        data = {'image_data': image_data}
        response = requests.post(url, data=data, timeout=TIMEOUT)
        
        print(f"状态码: {response.status_code}")
        print(f"响应长度: {len(response.text)}")
        print(f"响应内容: {response.text[:500]}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False


# ================== 测试3: /v1/completions ==================


def test_v1_completions():
    """测试 /v1/completions 接口"""
    print("\n" + "=" * 50)
    print("3. 测试 /v1/completions 接口")
    print("=" * 50)
    url = f"{GATEWAY_URL}/v1/completions"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    
    data = {
        "model": MODEL_NAME,
        "prompt": "你是谁",
        "max_tokens": 200,
        "temperature": 0.7,
        "stream": False
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=TIMEOUT)
        
        print(f"状态码: {response.status_code}")
        print(f"响应长度: {len(response.text)}")
        print(f"响应内容: {response.text[:500]}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False


# ================== 测试4: /v1/chat/completions 非流式 ==================


def test_v1_chat_completions_non_stream():
    """测试 /v1/chat/completions 非流式接口"""
    print("\n" + "=" * 50)
    print("4. 测试 /v1/chat/completions 非流式接口")
    print("=" * 50)
    url = f"{GATEWAY_URL}/v1/chat/completions"
    
    headers = {"Content-Type": "application/json"}
    
    data = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "user", "content": "你好"}
        ],
        "max_tokens": 200,
        "temperature": 0.7,
        "stream": False
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=TIMEOUT)
        
        print(f"状态码: {response.status_code}")
        print(f"响应长度: {len(response.text)}")
        print(f"响应内容: {response.text[:500]}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False


# ================== 测试5: /v1/chat/completions 流式 ==================


def test_v1_chat_completions_stream():
    """测试 /v1/chat/completions 流式接口"""
    print("\n" + "=" * 50)
    print("5. 测试 /v1/chat/completions 流式接口")
    print("=" * 50)
    url = f"{GATEWAY_URL}/v1/chat/completions"
    
    headers = {"Content-Type": "application/json"}
    
    data = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "user", "content": "你好"}
        ],
        "max_tokens": 200,
        "temperature": 0.7,
        "stream": True
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=TIMEOUT, stream=True)
        
        print(f"状态码: {response.status_code}")
        print("流式响应内容:")
        
        full_response = b""
        for chunk in response.iter_content(chunk_size=1024):
            if chunk:
                # print(chunk.decode('utf-8', errors='ignore'), end="")
                full_response += chunk
        
        print(f"\n\n总响应长度: {len(full_response)}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False


# ================== 测试6: 异常JSON格式 ==================


def test_invalid_json():
    """测试异常JSON格式 (Python风格 True/False/None)"""
    print("\n" + "=" * 50)
    print("6. 测试异常JSON格式 (Python风格)")
    print("=" * 50)
    url = f"{GATEWAY_URL}/v1/chat/completions"
    
    headers = {"Content-Type": "application/json"}
    
    # 使用 Python 风格的 True (应该返回错误)
    data = f"""{{
        "model": "{MODEL_NAME}",
        "messages": [
            {{
                "role": "user",
                "content": "你好"
            }}
        ],
        "max_tokens": 200,
        "temperature": 0.7,
        "stream": True
    }}"""
    
    try:
        response = requests.post(url, headers=headers, data=data.encode(), timeout=TIMEOUT)
        
        print(f"状态码: {response.status_code}")
        print(f"响应内容: {response.text[:500]}")
        # 期望返回错误响应
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False


# ================== 测试7: /v1/embeddings ==================


def test_v1_embeddings():
    """测试 /v1/embeddings 接口"""
    print("\n" + "=" * 50)
    print("7. 测试 /v1/embeddings 接口")
    print("=" * 50)
    url = f"{GATEWAY_URL}/v1/embeddings"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }
    
    data = {
        "model": "jina-clip-v1",
        "input": "你好，世界！",
        "parameters": {
            "task": "representation",
            "dimension": 768
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=TIMEOUT)
        
        print(f"状态码: {response.status_code}")
        print(f"响应长度: {len(response.text)}")
        print(f"响应内容: {response.text[:500]}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False


# ================== 测试8: 队列状态 ==================


def test_queue_status():
    """测试队列状态接口"""
    print("\n" + "=" * 50)
    print("8. 测试队列状态接口")
    print("=" * 50)
    url = f"{GATEWAY_URL}/queue/status"
    
    try:
        response = requests.get(url, timeout=TIMEOUT)
        
        print(f"状态码: {response.status_code}")
        print(f"响应内容: {response.text}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False


# ================== 测试9: 调度器监控 ==================


def test_scheduler_monitor():
    """测试调度器监控接口"""
    print("\n" + "=" * 50)
    print("9. 测试调度器监控接口")
    print("=" * 50)
    url = f"{GATEWAY_URL}/scheduler/monitor?minutes=10"
    
    try:
        response = requests.get(url, timeout=TIMEOUT)
        
        print(f"状态码: {response.status_code}")
        print(f"响应长度: {len(response.text)}")
        print(f"响应内容: {response.text[:500]}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False


def main():
    """运行所有测试"""
    print("\n" + "#" * 60)
    print("# LLM Gateway 测试脚本")
    print(f"# Gateway URL: {GATEWAY_URL}")
    print("#" * 60)
    
    results = {}
    
    # 运行测试
    results["OCR文件上传"] = test_ocr_file_upload()
    results["OCR Base64编码"] = test_ocr_base64()
    results["/v1/completions"] = test_v1_completions()
    results["/v1/chat/completions 非流式"] = test_v1_chat_completions_non_stream()
    results["/v1/chat/completions 流式"] = test_v1_chat_completions_stream()
    results["异常JSON格式"] = test_invalid_json()
    results["/v1/embeddings"] = test_v1_embeddings()
    results["队列状态"] = test_queue_status()
    results["调度器监控"] = test_scheduler_monitor()
    
    # 打印测试结果汇总
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    for test_name, success in results.items():
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{test_name}: {status}")
        if success:
            passed += 1
        else:
            failed += 1
    
    print("-" * 60)
    print(f"总计: {passed} 通过, {failed} 失败")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)