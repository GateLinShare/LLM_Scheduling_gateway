'use client'

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import axios from 'axios';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || '';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const router = useRouter();

  useEffect(() => {
    // 检查是否已经登录
    const cachedKey = localStorage.getItem('api_key');
    if (cachedKey) {
      // 验证缓存的 key 是否有效
      validateAndRedirect(cachedKey);
    }
  }, []);

  async function validateAndRedirect(key: string) {
    try {
      const response = await axios.get(`${API_BASE}/api/me`, {
        headers: { Authorization: `Bearer ${key}` },
        timeout: 10000,
      });
      if (response.data) {
        // Key 有效，跳转到主页
        router.push('/');
      }
    } catch (error) {
      // Key 无效，清除缓存
      localStorage.removeItem('api_key');
    }
  }

  async function handleLogin(event: React.FormEvent) {
    event.preventDefault();
    const user = username.trim();
    const pass = password.trim();
    if (!user || !pass) {
      setMessage('请输入用户名和密码');
      return;
    }

    setLoading(true);
    setMessage('');

    try {
      // 使用用户名和密码登录
      const response = await axios.post(`${API_BASE}/api/auth/login`, {
        username: user,
        password: pass,
      }, {
        timeout: 10000,
      });

      if (response.data && response.data.api_key) {
        // 登录成功，保存 API Key 到 localStorage
        localStorage.setItem('api_key', response.data.api_key);

        // 跳转到主页
        router.push('/');
      }
    } catch (error) {
      console.error('Login error:', error);
      if (axios.isAxiosError(error)) {
        if (error.message === 'Network Error') {
          setMessage('网络错误，无法连接到后端服务，请检查后端是否正常运行');
        } else if (error.response?.status === 401) {
          setMessage('用户名或密码错误');
        } else if (error.response?.status === 403) {
          setMessage('账号已被禁用');
        } else if (error.response?.status === 503) {
          setMessage('服务暂时不可用，请检查数据库配置');
        } else if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
          setMessage('请求超时，可能是数据库查询失败，请检查数据库配置和连接状态');
        } else if (error.code === 'ECONNREFUSED') {
          setMessage('连接被拒绝，请检查后端服务是否正常运行');
        } else {
          setMessage('登录失败：' + (error.response?.data?.detail || error.response?.data?.message || error.message));
        }
      } else {
        setMessage('登录失败：未知错误');
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-100 px-4">
      <div className="w-full max-w-md border border-zinc-300 bg-white p-8 shadow-lg">
        <h1 className="mb-6 text-center text-2xl font-bold text-zinc-900">LLM 调度网关</h1>
        <form onSubmit={handleLogin} className="space-y-4">
          <div>
            <label htmlFor="username" className="block text-sm font-medium text-zinc-700">
              用户名
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="mt-1 h-11 w-full border border-zinc-300 px-3 text-sm focus:border-zinc-500 focus:outline-none"
              placeholder="请输入用户名"
              disabled={loading}
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="password" className="block text-sm font-medium text-zinc-700">
              密码
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 h-11 w-full border border-zinc-300 px-3 text-sm focus:border-zinc-500 focus:outline-none"
              placeholder="请输入密码"
              disabled={loading}
              autoComplete="off"
            />
          </div>
          {message && (
            <div className={`rounded border px-3 py-2 text-sm ${
              message.includes('成功')
                ? 'border-green-300 bg-green-50 text-green-700'
                : 'border-red-300 bg-red-50 text-red-700'
            }`}>
              {message}
            </div>
          )}
          <button
            type="submit"
            disabled={loading}
            className="h-11 w-full bg-zinc-950 text-sm font-medium text-white hover:bg-zinc-800 disabled:cursor-not-allowed disabled:bg-zinc-400"
          >
            {loading ? '登录中...' : '登录'}
          </button>
        </form>
        <p className="mt-6 text-center text-xs text-zinc-500">
          请使用用户名和密码登录系统
        </p>
        <p className="mt-2 text-center text-xs text-zinc-400">
          忘记密码请联系{process.env.NEXT_PUBLIC_ADMIN_CONTACT || '管理员'}重置密码
        </p>
        <p className="mt-2 text-center text-xs text-zinc-400">
          密码经 bcrypt 加盐哈希存储，数据库中不保存明文
        </p>
      </div>
    </div>
  );
}
