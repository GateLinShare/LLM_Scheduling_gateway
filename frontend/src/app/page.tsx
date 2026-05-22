'use client'

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import axios, { AxiosInstance } from 'axios';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

interface MonitorData {
  model_name: string;
  timestamp: string;
  avg_gpu_usage: number;
  avg_num_requests_waiting: number;
  avg_pending_requests: number;
  avg_low_priority_pending_requests: number;
  avg_num_requests_running: number;
  avg_queue_length: number;
}

interface UsageRow {
  user_id: number | null;
  username: string;
  model_name: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  total_price: number;
  daily_price: number;
  request_count: number;
}

interface ConversationRow {
  id: number;
  created_at: string;
  username: string;
  model_name: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  user_prompt: string;
  assistant_response: string;
}

interface ModelDailyRow {
  day: string;
  model_name: string;
  prompt_tokens: number;
}

interface GPUInfo {
  index: number;
  model: string;
  memory_total_mb: number;
  memory_used_mb: number;
  memory_free_mb: number;
  memory_used_percent: number;
}

interface GPUServerData {
  [ip: string]: GPUInfo[] | string;
}

interface GPUResponse {
  servers: GPUServerData;
}

interface UserRow {
  id: number;
  username: string;
  role: string;
  priority: number;
  quota_unlimited: boolean;
  quota_limit: number | null;
  quota_used: number;
  enabled: boolean;
  auto_registered: boolean;
}

interface ModelConfig {
  api_url?: string;
  api_key?: string;
  model_name?: string;
  queue_name?: string;
  enabled?: boolean;
  tokenizer_model?: string;
  type?: string;
  price?: {
    input_per_1k?: number;
    output_per_1k?: number;
    currency?: string;
  };
  price_multipliers?: {
    weekday_peak?: number;
    weekday_flat?: number;
    night?: number;
    weekend?: number;
  };
  degrade?: {
    enabled?: boolean;
    api_url?: string;
    model_name?: string;
    api_key?: string;
  };
  queues?: ModelQueueConfig[];
  load_queue?: string;
  [key: string]: unknown;
}

interface ModelQueueConfig {
  queue_name?: string;
  api_url?: string;
  api_key?: string;
  model_name?: string;
  load_factor?: number;
}

type Tab = 'monitor' | 'usage' | 'modelStats' | 'gpu' | 'conversations' | 'models' | 'users' | 'password' | 'settings';
type TimeUnit = 'minutes' | 'days';
type ModelType = 'single' | 'multi-queue';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || '';
const COLORS = ['#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed', '#0f766e'];
const emptyModelForm = {
  api_url: '',
  api_key: '',
  model_name: '',
  queue_name: '',
  load_queue: '',
  enabled: true,
  tokenizer_model: 'gpt-3.5-turbo',
  input_per_1k: '0',
  output_per_1k: '0',
  currency: 'CNY',
  weekday_peak: '1.5',
  weekday_flat: '1.0',
  night: '0.3',
  weekend: '0.3',
  degrade_enabled: false,
  degrade_api_url: '',
  degrade_model_name: '',
  degrade_api_key: '',
};
const emptyQueueForm: ModelQueueConfig = {
  queue_name: '',
  api_url: '',
  api_key: '',
  model_name: '',
  load_factor: 1,
};

function sampleData<T>(data: T[], maxPoints: number): T[] {
  if (data.length <= maxPoints) return data;
  const step = Math.ceil(data.length / maxPoints);
  return data.filter((_, index) => index % step === 0);
}

function createClient(apiKey: string): AxiosInstance {
  return axios.create({
    baseURL: API_BASE,
    timeout: 30000,
    headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : undefined,
  });
}

export default function Home() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<Tab>('monitor');
  const [apiKey, setApiKey] = useState('');
  const [me, setMe] = useState<UserRow | null>(null);
  const [mounted, setMounted] = useState(false);
  const [timeValue, setTimeValue] = useState(30);
  const [timeUnit, setTimeUnit] = useState<TimeUnit>('days');
  const [filterModel, setFilterModel] = useState('');
  const [filterUserId, setFilterUserId] = useState('');
  const [filterUsername, setFilterUsername] = useState('');
  const [conversationLimit, setConversationLimit] = useState(100);
  const [userRoleFilter, setUserRoleFilter] = useState('');
  const [userPriorityFilter, setUserPriorityFilter] = useState('');
  const [userPage, setUserPage] = useState(1);
  const USER_PAGE_SIZE = 100;
  const [monitorData, setMonitorData] = useState<MonitorData[]>([]);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState('');
  const [usageRows, setUsageRows] = useState<UsageRow[]>([]);
  const [conversationRows, setConversationRows] = useState<ConversationRow[]>([]);
  const [modelDailyRows, setModelDailyRows] = useState<ModelDailyRow[]>([]);
  const [modelsJson, setModelsJson] = useState('{}');
  const [configJson, setConfigJson] = useState('{}');
  const [users, setUsers] = useState<UserRow[]>([]);
  const [newUsername, setNewUsername] = useState('');
  const [newPriority, setNewPriority] = useState(3);
  const [newQuotaUnlimited, setNewQuotaUnlimited] = useState(true);
  const [newQuotaLimit, setNewQuotaLimit] = useState('');
  const [modelName, setModelName] = useState('');
  const [editingModel, setEditingModel] = useState('');
  const [modelForm, setModelForm] = useState(emptyModelForm);
  const [modelType, setModelType] = useState<ModelType>('single');
  const [modelQueues, setModelQueues] = useState<ModelQueueConfig[]>([{ ...emptyQueueForm }]);
  const [modelModalOpen, setModelModalOpen] = useState(false);
  const [lastKey, setLastKey] = useState('');
  const [message, setMessage] = useState('');
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null);
  const [loading, setLoading] = useState(false);
  const [autoRegisterEnabled, setAutoRegisterEnabled] = useState(false);
  const [rateLimitWindowMinutes, setRateLimitWindowMinutes] = useState(1);
  const [rateLimitRequestThreshold, setRateLimitRequestThreshold] = useState(5);
  const [rateLimitDowngradedPriority, setRateLimitDowngradedPriority] = useState(4);
  const [dailyQuotaLimit, setDailyQuotaLimit] = useState(20);
  const [windowQuotaLimit, setWindowQuotaLimit] = useState(0.36);
  const [windowQuotaAction, setWindowQuotaAction] = useState('limit');
  const [dailyQuotaAction, setDailyQuotaAction] = useState('limit');
  const [tokenCacheDir, setTokenCacheDir] = useState('');
  const [defaultTokenizerModel, setDefaultTokenizerModel] = useState('gpt-3.5-turbo');
  const [systemTimeMinute, setSystemTimeMinute] = useState('');
  const [timeOffsetMinutes, setTimeOffsetMinutes] = useState(0);
  const [timeoutHighPriority, setTimeoutHighPriority] = useState(600);
  const [timeoutLowPriority, setTimeoutLowPriority] = useState(7200);
  const [gpuThreshold, setGpuThreshold] = useState(0.7);
  const [schedulerHighLowRatio, setSchedulerHighLowRatio] = useState(5);
  const [schedulerSleepInterval, setSchedulerSleepInterval] = useState(0.2);
  const [schedulerMinWaitingRequests, setSchedulerMinWaitingRequests] = useState(2);
  const [schedulerMaxPendingRequests, setSchedulerMaxPendingRequests] = useState(30);
  const [schedulerLowPriorityMaxPending, setSchedulerLowPriorityMaxPending] = useState(3);
  const [schedulerDefaultPriority, setSchedulerDefaultPriority] = useState(3);
  const [schedulerHighPriorityMax, setSchedulerHighPriorityMax] = useState(3);
  const [schedulerLowPriorityMin, setSchedulerLowPriorityMin] = useState(4);
  const [gpuData, setGpuData] = useState<GPUServerData>({});
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [confirmDialog, setConfirmDialog] = useState<{ show: boolean; message: string; onConfirm: () => void } | null>(null);

  const client = useMemo(() => createClient(apiKey), [apiKey]);
  const isAdmin = me?.role === 'admin';
  const visibleTabs = useMemo<Tab[]>(
    () => isAdmin ? ['monitor', 'usage', 'modelStats', 'gpu', 'conversations', 'models', 'users', 'password', 'settings'] : ['monitor', 'usage', 'modelStats', 'users', 'password'],
    [isAdmin],
  );
  const filterQuery = useMemo(() => {
    const params = new URLSearchParams();
    params.set(timeUnit, String(timeValue));
    if (filterModel) params.set('model_name', filterModel);
    if (isAdmin && filterUserId) params.set('user_id', filterUserId);
    if (isAdmin && filterUsername.trim()) params.set('username', filterUsername.trim());
    return params.toString();
  }, [filterModel, filterUserId, filterUsername, isAdmin, timeUnit, timeValue]);

  const showToast = useCallback((message: string, type: 'success' | 'error' | 'info' = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  }, []);

  const fetchMe = useCallback(async () => {
    if (!apiKey) {
      setMe(null);
      setUsers([]);
      return null;
    }
    try {
      const response = await client.get('/api/me');
      setMe(response.data);
      if (response.data.auto_registered) setAutoRegisterEnabled(true);
      return response.data as UserRow;
    } catch (error) {
      setMe(null);
      setUsers([]);
      // 如果 API Key 无效，清除缓存并跳转到登录页
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        localStorage.removeItem('api_key');
        if (mounted) {
          router.push('/login');
        }
      }
      return null;
    }
  }, [apiKey, client, mounted, router]);

  const fetchMonitor = useCallback(async () => {
    const response = await axios.get(`${API_BASE}/api/scheduler/monitor?minutes=120`, { timeout: 30000 });
    const rows: MonitorData[] = response.data.data || [];
    setMonitorData(rows);
    const models = Array.from(new Set(rows.map((item) => item.model_name)));
    if (models.length > 0) {
      setSelectedModel((current) => current || models[0]);
    }
  }, []);

  const fetchAvailableModels = useCallback(async () => {
    const response = await axios.get(`${API_BASE}/v1/models`, { timeout: 30000 });
    setAvailableModels((response.data.data || []).map((item: { id: string }) => item.id).filter(Boolean));
  }, []);

  const fetchUsage = useCallback(async () => {
    if (!apiKey) return;
    const response = await client.get(`/api/usage/summary?${filterQuery}`);
    setUsageRows(response.data.data || []);
  }, [apiKey, client, filterQuery]);

  const fetchModelDaily = useCallback(async () => {
    if (!apiKey) return;
    const response = await client.get('/api/usage/model-hourly');
    setModelDailyRows(response.data.data || []);
  }, [apiKey, client]);

  const fetchConversations = useCallback(async () => {
    if (!apiKey) return;
    const limit = Math.max(1, Math.min(500, conversationLimit || 100));
    const response = await client.get(`/api/usage/conversations?${filterQuery}&limit=${limit}`);
    setConversationRows(response.data.data || []);
  }, [apiKey, client, conversationLimit, filterQuery]);

  const fetchModels = useCallback(async () => {
    if (!apiKey) return;
    const response = await client.get('/api/admin/models');
    setModelsJson(JSON.stringify(response.data, null, 2));
  }, [apiKey, client]);

  const fetchConfig = useCallback(async () => {
    if (!apiKey) return;
    const response = await client.get('/api/admin/config');
    setConfigJson(JSON.stringify(response.data, null, 2));
    setAutoRegisterEnabled(Boolean(response.data?.features?.auto_register_enabled));
    setRateLimitWindowMinutes(Number(response.data?.rate_limit?.window_minutes ?? 1));
    setRateLimitRequestThreshold(Number(response.data?.rate_limit?.request_threshold ?? 5));
    setRateLimitDowngradedPriority(Number(response.data?.rate_limit?.downgraded_priority ?? 4));
    setDailyQuotaLimit(Number(response.data?.rate_limit?.daily_quota_limit ?? 20));
    setWindowQuotaLimit(Number(response.data?.rate_limit?.window_quota_limit ?? 0.36));
    setWindowQuotaAction(String(response.data?.rate_limit?.window_quota_action ?? 'limit'));
    setDailyQuotaAction(String(response.data?.rate_limit?.daily_quota_action ?? 'limit'));
    setTokenCacheDir(String(response.data?.token?.tiktoken_cache_dir ?? ''));
    setDefaultTokenizerModel(String(response.data?.token?.default_tokenizer_model ?? 'gpt-3.5-turbo'));
    setTimeOffsetMinutes(Number(response.data?.system?.time_offset_minutes ?? 0));
    setTimeoutHighPriority(Number(response.data?.scheduler?.timeouts?.high_priority ?? 600));
    setTimeoutLowPriority(Number(response.data?.scheduler?.timeouts?.low_priority ?? 7200));
    setGpuThreshold(Number(response.data?.scheduler?.gpu_threshold ?? 0.7));
    setSchedulerHighLowRatio(Number(response.data?.scheduler?.high_low_ratio ?? 5));
    setSchedulerSleepInterval(Number(response.data?.scheduler?.sleep_interval ?? 0.2));
    setSchedulerMinWaitingRequests(Number(response.data?.scheduler?.min_waiting_requests ?? 2));
    setSchedulerMaxPendingRequests(Number(response.data?.scheduler?.max_pending_requests ?? 30));
    setSchedulerLowPriorityMaxPending(Number(response.data?.scheduler?.low_priority_max_pending ?? 3));
    setSchedulerDefaultPriority(Number(response.data?.scheduler?.default_priority ?? 3));
    setSchedulerHighPriorityMax(Number(response.data?.scheduler?.priority_thresholds?.high_priority_max ?? 3));
    setSchedulerLowPriorityMin(Number(response.data?.scheduler?.priority_thresholds?.low_priority_min ?? 4));
    const timeResponse = await client.get('/api/admin/system-time');
    setSystemTimeMinute(String(timeResponse.data?.system_time_minute ?? ''));
  }, [apiKey, client]);

  const fetchAdminUsers = useCallback(async () => {
    if (!apiKey) return;
    const response = await client.get('/api/admin/users');
    setUsers(response.data.data || []);
  }, [apiKey, client]);

  const fetchGPUInfo = useCallback(async () => {
    const response = await axios.get(`${API_BASE}/api/gpu/info`, { timeout: 30000 });
    setGpuData(response.data.servers || {});
  }, []);

  const fetchUsers = useCallback(async (currentUser?: UserRow | null) => {
    if (!apiKey) {
      setUsers([]);
      return;
    }
    const userForRole = currentUser;
    if (userForRole?.role === 'admin') {
      await fetchAdminUsers();
      return;
    }
    if (userForRole) {
      setUsers([userForRole]);
      return;
    }
    setUsers([]);
  }, [apiKey, fetchAdminUsers]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setMessage('');
    try {
      const currentUser = await fetchMe();
      const currentIsAdmin = currentUser?.role === 'admin';
      const currentTabs: Tab[] = currentIsAdmin
        ? ['monitor', 'usage', 'modelStats', 'gpu', 'conversations', 'models', 'users', 'password', 'settings']
        : ['monitor', 'usage', 'modelStats', 'users', 'password'];
      if (!currentTabs.includes(activeTab)) {
        setActiveTab('usage');
        return;
      }
      if (activeTab === 'monitor') await fetchMonitor();
      if (activeTab === 'usage' || (currentIsAdmin && activeTab === 'conversations')) await fetchAvailableModels();
      if (activeTab === 'usage') await fetchUsage();
      if (activeTab === 'modelStats') await fetchModelDaily();
      if (currentIsAdmin && activeTab === 'gpu') await fetchGPUInfo();
      if (currentIsAdmin && activeTab === 'conversations') await fetchConversations();
      if (activeTab === 'usage' || activeTab === 'users' || (currentIsAdmin && activeTab === 'conversations')) await fetchUsers(currentUser);
      if (currentIsAdmin && activeTab === 'models') await fetchModels();
      if (currentIsAdmin && (activeTab === 'settings' || activeTab === 'users')) await fetchConfig();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '请求失败');
    } finally {
      setLoading(false);
    }
  }, [activeTab, fetchAvailableModels, fetchConfig, fetchConversations, fetchGPUInfo, fetchMe, fetchModelDaily, fetchModels, fetchMonitor, fetchUsage, fetchUsers]);

  useEffect(() => {
    setMounted(true);
    // 从 localStorage 加载 API Key
    const cachedKey = localStorage.getItem('api_key');
    if (cachedKey) {
      setApiKey(cachedKey);
    } else {
      // 没有缓存的 key，跳转到登录页
      router.push('/login');
    }
  }, [router]);

  useEffect(() => {
    // 当 API Key 变化时，保存到 localStorage
    if (apiKey && mounted) {
      localStorage.setItem('api_key', apiKey);
    }
  }, [apiKey, mounted]);

  useEffect(() => {
    setUserPage(1);
  }, [filterUsername, userRoleFilter, userPriorityFilter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const visibleMonitorData = useMemo(() => {
    const rows = selectedModel ? monitorData.filter((item) => item.model_name === selectedModel) : monitorData;
    return sampleData(rows.map((item) => ({
      timestamp: item.timestamp,
      gpu_usage: Math.min(1, Math.max(0, item.avg_gpu_usage)),
      wait: item.avg_num_requests_waiting,
      run: item.avg_num_requests_running,
      norsp: item.avg_pending_requests,
      lnorsp: item.avg_low_priority_pending_requests,
      queue: item.avg_queue_length,
    })), 200);
  }, [monitorData, selectedModel]);

  const modelNames = useMemo(() => Array.from(new Set(monitorData.map((item) => item.model_name))), [monitorData]);
  const configuredModels = useMemo<Record<string, ModelConfig>>(() => {
    try {
      return JSON.parse(modelsJson) as Record<string, ModelConfig>;
    } catch {
      return {};
    }
  }, [modelsJson]);
  const configuredModelNames = useMemo(() => {
    return Object.keys(configuredModels);
  }, [configuredModels]);
  const filterModelNames = configuredModelNames.length > 0 ? configuredModelNames : (availableModels.length > 0 ? availableModels : modelNames);
  const filteredUsers = useMemo(() => {
    return users.filter((user) => {
      if (userRoleFilter && user.role !== userRoleFilter) return false;
      if (userPriorityFilter && String(user.priority ?? 3) !== userPriorityFilter) return false;
      if (filterUsername && !user.username.toLowerCase().includes(filterUsername.toLowerCase())) return false;
      return true;
    });
  }, [filterUsername, userPriorityFilter, userRoleFilter, users]);

  const totalUserPages = useMemo(() => Math.max(1, Math.ceil(filteredUsers.length / USER_PAGE_SIZE)), [filteredUsers, USER_PAGE_SIZE]);
  const paginatedUsers = useMemo(() => {
    const page = Math.min(userPage, totalUserPages);
    const start = (page - 1) * USER_PAGE_SIZE;
    return filteredUsers.slice(start, start + USER_PAGE_SIZE);
  }, [filteredUsers, userPage, totalUserPages, USER_PAGE_SIZE]);

  function openCreateModel() {
    resetModelForm();
    setModelModalOpen(true);
  }

  function editModel(name: string, config: ModelConfig) {
    setEditingModel(name);
    setModelName(name);
    const nextType: ModelType = config.type === 'multi-queue' ? 'multi-queue' : 'single';
    setModelType(nextType);
    setModelQueues(
      nextType === 'multi-queue' && config.queues?.length
        ? config.queues.map((queue) => ({
          queue_name: queue.queue_name || '',
          api_url: queue.api_url || '',
          api_key: queue.api_key || '',
          model_name: queue.model_name || '',
          load_factor: Number(queue.load_factor ?? 1),
        }))
        : [{ ...emptyQueueForm }],
    );
    setModelForm({
      api_url: config.api_url || '',
      api_key: config.api_key || '',
      model_name: config.model_name || '',
      queue_name: config.queue_name || '',
      load_queue: config.load_queue || `${name}-load-queue`,
      enabled: config.enabled ?? true,
      tokenizer_model: config.tokenizer_model || 'gpt-3.5-turbo',
      input_per_1k: String(config.price?.input_per_1k ?? 0),
      output_per_1k: String(config.price?.output_per_1k ?? 0),
      currency: config.price?.currency || 'CNY',
      weekday_peak: String(config.price_multipliers?.weekday_peak ?? 1.5),
      weekday_flat: String(config.price_multipliers?.weekday_flat ?? 1.0),
      night: String(config.price_multipliers?.night ?? 0.3),
      weekend: String(config.price_multipliers?.weekend ?? 0.3),
      degrade_enabled: config.degrade?.enabled ?? false,
      degrade_api_url: config.degrade?.api_url || '',
      degrade_model_name: config.degrade?.model_name || '',
      degrade_api_key: config.degrade?.api_key || '',
    });
    setModelModalOpen(true);
  }

  function resetModelForm() {
    setEditingModel('');
    setModelName('');
    setModelForm(emptyModelForm);
    setModelType('single');
    setModelQueues([{ ...emptyQueueForm }]);
  }

  function closeModelModal() {
    setModelModalOpen(false);
    resetModelForm();
  }

  function updateModelQueue(index: number, patch: Partial<ModelQueueConfig>) {
    setModelQueues((queues) => queues.map((queue, queueIndex) => queueIndex === index ? { ...queue, ...patch } : queue));
  }

  function addModelQueue() {
    setModelQueues((queues) => [...queues, { ...emptyQueueForm }]);
  }

  function removeModelQueue(index: number) {
    setModelQueues((queues) => queues.length > 1 ? queues.filter((_, queueIndex) => queueIndex !== index) : queues);
  }

  async function saveModel() {
    const name = modelName.trim();
    if (!name) {
      setMessage('模型名称不能为空');
      return;
    }
    const basePayload: ModelConfig = {
      enabled: modelForm.enabled,
      tokenizer_model: modelForm.tokenizer_model.trim() || 'gpt-3.5-turbo',
      api_key: modelForm.api_key.trim(),
      price: {
        input_per_1k: Number(modelForm.input_per_1k || 0),
        output_per_1k: Number(modelForm.output_per_1k || 0),
        currency: modelForm.currency.trim() || 'CNY',
      },
      price_multipliers: {
        weekday_peak: Number(modelForm.weekday_peak || 1.5),
        weekday_flat: Number(modelForm.weekday_flat || 1.0),
        night: Number(modelForm.night || 0.3),
        weekend: Number(modelForm.weekend || 0.3),
      },
      degrade: modelForm.degrade_enabled ? {
        enabled: true,
        api_url: modelForm.degrade_api_url.trim(),
        model_name: modelForm.degrade_model_name.trim(),
        api_key: modelForm.degrade_api_key.trim(),
      } : {
        enabled: false,
      },
    };
    let payload: ModelConfig;
    if (modelType === 'multi-queue') {
      const queues = modelQueues
        .map((queue) => ({
          queue_name: queue.queue_name?.trim() || '',
          api_url: queue.api_url?.trim() || '',
          api_key: queue.api_key?.trim() || '',
          model_name: queue.model_name?.trim() || name,
          load_factor: Number(queue.load_factor ?? 1),
        }))
        .filter((queue) => queue.queue_name && queue.api_url);
      if (queues.length === 0) {
        setMessage('多队列模型至少需要一个有效队列，且队列名和 API URL 不能为空');
        return;
      }
      payload = {
        ...basePayload,
        type: 'multi-queue',
        queues,
        load_queue: modelForm.load_queue.trim() || `${name}-load-queue`,
      };
    } else {
      payload = {
        ...basePayload,
        api_url: modelForm.api_url.trim(),
        model_name: modelForm.model_name.trim() || name,
        queue_name: modelForm.queue_name.trim() || name,
      };
      delete payload.type;
      delete payload.queues;
      delete payload.load_queue;
    }
    if (editingModel && editingModel !== name) {
      await client.delete(`/api/admin/models/${encodeURIComponent(editingModel)}`);
    }
    // 新增和更新都走 PUT，避免 POST 的 model_name 字段与下游模型名字段冲突。
    await client.put(`/api/admin/models/${encodeURIComponent(name)}`, payload);
    showToast('模型配置已保存');
    closeModelModal();
    await fetchModels();
  }

  async function deleteModel(name: string) {
    await client.delete(`/api/admin/models/${encodeURIComponent(name)}`);
    if (editingModel === name) closeModelModal();
    setMessage('模型配置已删除');
    await fetchModels();
  }

  async function restartGateway() {
    if (!window.confirm('确认重启网关吗？重启会使新配置生效，期间服务可能短暂不可用。')) return;
    try {
      await client.post('/api/admin/gateway/restart');
      setMessage('网关重启命令已触发');
    } catch {
      setMessage('网关重启命令已触发，连接中断属于正常现象');
    }
    window.setTimeout(() => {
      void waitGatewayRestart();
    }, 1000);
  }

  async function waitGatewayRestart() {
    setMessage('网关重启中，正在等待后端恢复...');
    for (let index = 0; index < 30; index += 1) {
      try {
        await axios.get(`${API_BASE}/api/scheduler/monitor?minutes=1`, { timeout: 2000 });
        setMessage('网关重启成功');
        return;
      } catch {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
      }
    }
    setMessage('网关重启命令已触发，但暂未检测到后端恢复');
  }

  async function saveConfig() {
    const config = JSON.parse(configJson || '{}');
    await client.put('/api/admin/config', {
      ...config,
      features: {
        ...(config.features || {}),
        auto_register_enabled: autoRegisterEnabled,
      },
      token: {
        ...(config.token || {}),
        tiktoken_cache_dir: tokenCacheDir,
        default_tokenizer_model: defaultTokenizerModel,
      },
      rate_limit: {
        window_minutes: Math.max(1, Number(rateLimitWindowMinutes || 1)),
        request_threshold: Math.max(0, Number(rateLimitRequestThreshold || 0)),
        downgraded_priority: Math.max(1, Math.min(5, Number(rateLimitDowngradedPriority || 4))),
        daily_quota_limit: Number(dailyQuotaLimit ?? 20),
        window_quota_limit: Number(windowQuotaLimit ?? 0.36),
        window_quota_action: windowQuotaAction || 'limit',
        daily_quota_action: dailyQuotaAction || 'limit',
      },
      system: {
        ...(config.system || {}),
        time_offset_minutes: Number(timeOffsetMinutes || 0),
      },
      scheduler: {
        ...(config.scheduler || {}),
        timeouts: {
          high_priority: Math.max(1, Number(timeoutHighPriority || 600)),
          low_priority: Math.max(1, Number(timeoutLowPriority || 7200)),
        },
        gpu_threshold: Math.max(0, Number(gpuThreshold || 0)),
        high_low_ratio: Math.max(1, Number(schedulerHighLowRatio || 5)),
        sleep_interval: Math.max(0.01, Number(schedulerSleepInterval || 0.2)),
        min_waiting_requests: Math.max(0, Number(schedulerMinWaitingRequests || 0)),
        max_pending_requests: Math.max(0, Number(schedulerMaxPendingRequests || 0)),
        low_priority_max_pending: Math.max(0, Number(schedulerLowPriorityMaxPending || 0)),
        default_priority: Math.max(1, Math.min(5, Number(schedulerDefaultPriority || 3))),
        priority_thresholds: {
          high_priority_max: Math.max(1, Math.min(5, Number(schedulerHighPriorityMax || 3))),
          low_priority_min: Math.max(1, Math.min(5, Number(schedulerLowPriorityMin || 4))),
        },
      },
    });
    showToast('系统配置已保存');
    await fetchConfig();
  }

  async function createUser() {
    if (!newUsername.trim()) return;
    const response = await client.post('/api/admin/users', {
      username: newUsername.trim(),
      role: 'user',
      priority: newPriority,
      quota_unlimited: newQuotaUnlimited,
      quota_limit: newQuotaUnlimited || !newQuotaLimit ? null : Number(newQuotaLimit),
    });
    setLastKey(response.data.api_key);
    setNewUsername('');
    setNewPriority(3);
    setNewQuotaUnlimited(true);
    setNewQuotaLimit('');
    await fetchAdminUsers();
  }

  async function updateUser(user: UserRow, patch: Partial<UserRow>) {
    if (!isAdmin) return;
    await client.put(`/api/admin/users/${user.id}`, patch);
    await fetchAdminUsers();
  }

  async function resetKey(user: UserRow) {
    if (autoRegisterEnabled) return;

    const confirmMessage = isAdmin
      ? `确认重置用户 ${user.username} 的 API Key？重置后旧密钥将失效。`
      : '确认重置您的 API Key？重置后旧密钥将失效，您需要更新所有使用该密钥的应用。';

    setConfirmDialog({
      show: true,
      message: confirmMessage,
      onConfirm: async () => {
        try {
          const response = isAdmin
            ? await client.post(`/api/admin/users/${user.id}/reset-key`)
            : await client.post('/api/users/me/reset-key');
          setLastKey(response.data.api_key);
          showToast('API Key 重置成功', 'success');
        } catch (error) {
          if (axios.isAxiosError(error)) {
            showToast(error.response?.data?.detail || 'API Key 重置失败', 'error');
          } else {
            showToast('API Key 重置失败', 'error');
          }
        }
        setConfirmDialog(null);
      }
    });
  }

  async function resetPassword(user: UserRow) {
    if (!isAdmin) return;

    setConfirmDialog({
      show: true,
      message: `确认重置用户 ${user.username} 的密码为默认值 123456？`,
      onConfirm: async () => {
        try {
          await client.post(`/api/admin/users/${user.id}/reset-password`);
          showToast(`用户 ${user.username} 的密码已重置为 123456`, 'success');
        } catch (error) {
          if (axios.isAxiosError(error)) {
            showToast(error.response?.data?.detail || '密码重置失败', 'error');
          } else {
            showToast('密码重置失败', 'error');
          }
        }
        setConfirmDialog(null);
      }
    });
  }

  async function handleChangePassword() {
    if (!oldPassword || !newPassword || !confirmPassword) {
      showToast('请填写所有密码字段', 'error');
      return;
    }
    if (newPassword !== confirmPassword) {
      showToast('两次输入的新密码不一致', 'error');
      return;
    }
    if (newPassword.length < 6) {
      showToast('密码长度至少为6位', 'error');
      return;
    }
    try {
      await client.post('/api/users/me/change-password', {
        old_password: oldPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
      showToast('密码修改成功，请重新登录', 'success');
      setOldPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setTimeout(() => {
        handleLogout();
      }, 2000);
    } catch (error) {
      if (axios.isAxiosError(error)) {
        showToast(error.response?.data?.detail || '密码修改失败', 'error');
      } else {
        showToast('密码修改失败', 'error');
      }
    }
  }

  function handleLogout() {
    // 清除 localStorage 中的 API Key
    localStorage.removeItem('api_key');
    // 清除状态
    setApiKey('');
    setMe(null);
    setUsers([]);
    // 跳转到登录页
    router.push('/login');
  }

  return (
    <main className="min-h-screen bg-[#eef1f5] text-zinc-950">
      {confirmDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
          <div className="min-w-[400px] max-w-md border border-zinc-300 bg-white p-6 shadow-2xl">
            <h3 className="mb-4 text-lg font-semibold text-zinc-900">确认操作</h3>
            <p className="mb-6 text-sm text-zinc-700">{confirmDialog.message}</p>
            <div className="flex justify-end gap-3">
              <button
                onClick={() => setConfirmDialog(null)}
                className="border border-zinc-300 bg-white px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50"
              >
                取消
              </button>
              <button
                onClick={confirmDialog.onConfirm}
                className="bg-zinc-950 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800"
              >
                确认
              </button>
            </div>
          </div>
        </div>
      )}
      {toast && (
        <div className="fixed inset-0 z-50 flex items-center justify-center pointer-events-none">
          <div className={`min-w-[320px] max-w-md animate-fade-in border px-6 py-4 shadow-2xl pointer-events-auto ${
            toast.type === 'success' ? 'border-green-400 bg-green-50 text-green-800' :
            toast.type === 'error' ? 'border-red-400 bg-red-50 text-red-800' :
            'border-blue-400 bg-blue-50 text-blue-800'
          }`}>
            <div className="flex items-center justify-between gap-4">
              <span className="text-base font-medium">{toast.message}</span>
              <button onClick={() => setToast(null)} className="text-2xl leading-none opacity-60 hover:opacity-100">&times;</button>
            </div>
          </div>
        </div>
      )}
      <div className="mx-auto max-w-7xl px-5 py-6">
        <header className="mb-5 flex flex-col gap-4 border-b border-zinc-300 bg-white px-5 py-4 shadow-sm lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-normal">LLM 调度网关控制台</h1>
            <p className="mt-1 text-sm text-zinc-600">{me ? `${me.username} · ${me.role}` : '加载中...'}</p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <button onClick={refresh} disabled={loading} className="h-10 bg-zinc-950 px-4 text-sm font-medium text-white disabled:bg-zinc-400">{loading ? '刷新中' : '刷新'}</button>
            <button onClick={handleLogout} className="h-10 border border-red-300 bg-white px-4 text-sm font-medium text-red-700 hover:bg-red-50">退出登录</button>
          </div>
        </header>

        <nav className="mb-5 flex flex-wrap gap-2">
          {visibleTabs.map((tab) => (
            <button key={tab} onClick={() => setActiveTab(tab)} className={`h-9 border px-3 text-sm shadow-sm ${activeTab === tab ? 'border-zinc-950 bg-zinc-950 text-white' : 'border-zinc-300 bg-white text-zinc-800 hover:border-zinc-500'}`}>
              {{ monitor: '调度监控', usage: '用量统计', modelStats: '模型统计', gpu: '显卡信息', conversations: '对话记录', models: '模型配置', users: '用户管理', password: '密码管理', settings: '系统设置' }[tab]}
            </button>
          ))}
        </nav>

        {message && <div className="mb-4 border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">{message}</div>}

        {(activeTab === 'usage' || (isAdmin && activeTab === 'conversations')) && (
          <section className="mb-4 flex flex-wrap items-center gap-2 border border-zinc-300 bg-white p-3 shadow-sm">
            <button onClick={() => { setTimeUnit('minutes'); setTimeValue(60); }} className="border border-zinc-300 bg-white px-3 py-2 text-sm">最近 60 分钟</button>
            <button onClick={() => { setTimeUnit('days'); setTimeValue(30); }} className="border border-zinc-300 bg-white px-3 py-2 text-sm">最近 30 天</button>
            <input type="number" min={1} value={timeValue} onChange={(event) => setTimeValue(Number(event.target.value))} className="h-10 w-28 border border-zinc-300 px-3 text-sm" />
            <select value={timeUnit} onChange={(event) => setTimeUnit(event.target.value as TimeUnit)} className="h-10 border border-zinc-300 bg-white px-3 text-sm">
              <option value="minutes">分钟</option>
              <option value="days">天</option>
            </select>
            <select value={filterModel} onChange={(event) => setFilterModel(event.target.value)} className="h-10 border border-zinc-300 bg-white px-3 text-sm">
              <option value="">全部模型</option>
              {filterModelNames.map((model) => <option key={model} value={model}>{model}</option>)}
            </select>
            {isAdmin && (
              <select value={filterUserId} onChange={(event) => { setFilterUserId(event.target.value); setFilterUsername(''); }} className="h-10 border border-zinc-300 bg-white px-3 text-sm">
                <option value="">全部用户</option>
                {users.map((user) => <option key={user.id} value={user.id}>{user.username}</option>)}
              </select>
            )}
            {isAdmin && (
              <input value={filterUsername} onChange={(event) => { setFilterUsername(event.target.value); setFilterUserId(''); }} placeholder="用户名过滤" className="h-10 w-44 border border-zinc-300 px-3 text-sm" />
            )}
            {isAdmin && activeTab === 'conversations' && (
              <label className="flex h-10 items-center gap-2 border border-zinc-300 bg-white px-3 text-sm">
                展示条数
                <input type="number" min={1} max={500} value={conversationLimit} onChange={(event) => setConversationLimit(Number(event.target.value))} className="h-8 w-20 border border-zinc-300 px-2 text-sm" />
              </label>
            )}
            <button onClick={refresh} className="border border-zinc-950 bg-zinc-950 px-3 py-2 text-sm text-white">应用过滤</button>
          </section>
        )}

        {activeTab === 'monitor' && (
          <section className="space-y-5">
            <div className="flex flex-wrap items-center gap-3">
              <select value={selectedModel} onChange={(event) => setSelectedModel(event.target.value)} className="h-10 border border-zinc-300 bg-white px-3 text-sm">
                {modelNames.map((model) => <option key={model} value={model}>{model}</option>)}
              </select>
            </div>
            <Chart title="GPU 利用率" data={visibleMonitorData} lines={[{ key: 'gpu_usage', name: 'GPU', color: COLORS[0] }]} percent mounted={mounted} />
            <Chart title="队列状态" data={visibleMonitorData} lines={[
              { key: 'wait', name: '模型等待', color: COLORS[0] },
              { key: 'run', name: '模型运行', color: COLORS[1] },
              { key: 'norsp', name: '高优先级未响应', color: COLORS[2] },
              { key: 'lnorsp', name: '低优先级未响应', color: COLORS[3] },
              { key: 'queue', name: '网关排队', color: COLORS[4] },
            ]} mounted={mounted} />
          </section>
        )}

        {activeTab === 'usage' && <UsageTable rows={usageRows} />}
        {activeTab === 'modelStats' && <ModelDailyChart rows={modelDailyRows} mounted={mounted} />}
        {activeTab === 'gpu' && isAdmin && <GPUMonitor servers={gpuData} />}
        {activeTab === 'conversations' && isAdmin && <ConversationList rows={conversationRows} />}

        {activeTab === 'models' && !isAdmin && <AdminHint />}
        {activeTab === 'models' && isAdmin && (
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">模型配置</h2>
              <div className="flex gap-2">
                <button onClick={restartGateway} title="重启会使新配置生效" className="border border-zinc-950 bg-white px-4 py-2 text-sm font-medium text-zinc-950">重启网关</button>
                <button onClick={openCreateModel} className="bg-zinc-950 px-4 py-2 text-sm font-medium text-white">新增模型</button>
              </div>
            </div>
            <ModelTable rows={configuredModels} onEdit={editModel} onDelete={deleteModel} />
            {modelModalOpen && (
              <ModelModal
                editingModel={editingModel}
                modelName={modelName}
                modelForm={modelForm}
                modelType={modelType}
                modelQueues={modelQueues}
                onClose={closeModelModal}
                onSave={saveModel}
                onModelNameChange={setModelName}
                onModelFormChange={setModelForm}
                onModelTypeChange={setModelType}
                onQueueChange={updateModelQueue}
                onQueueAdd={addModelQueue}
                onQueueRemove={removeModelQueue}
              />
            )}
          </section>
        )}

        {activeTab === 'users' && (
          <section className="space-y-4">
            {isAdmin && <div className="flex flex-wrap gap-2">
              <input value={newUsername} onChange={(event) => setNewUsername(event.target.value)} placeholder="新用户名" className="h-10 border border-zinc-300 px-3 text-sm" />
              <select value={newPriority} onChange={(event) => setNewPriority(Number(event.target.value))} className="h-10 border border-zinc-300 bg-white px-3 text-sm">
                {[1, 2, 3, 4, 5].map((priority) => <option key={priority} value={priority}>优先级 {priority}</option>)}
              </select>
              <label className="flex h-10 items-center gap-2 border border-zinc-300 bg-white px-3 text-sm">
                <input type="checkbox" checked={newQuotaUnlimited} onChange={(event) => setNewQuotaUnlimited(event.target.checked)} />
                无限额度
              </label>
              <input type="number" min={0} step="0.000001" disabled={newQuotaUnlimited} value={newQuotaLimit} onChange={(event) => setNewQuotaLimit(event.target.value)} placeholder="额度上限" className="h-10 border border-zinc-300 px-3 text-sm disabled:bg-zinc-100" />
              <button onClick={createUser} className="bg-zinc-950 px-4 py-2 text-sm font-medium text-white">创建用户</button>
            </div>}
            {isAdmin && (
              <div className="flex flex-wrap items-center gap-2 border border-zinc-300 bg-white p-3">
                <input value={filterUsername} onChange={(event) => setFilterUsername(event.target.value)} placeholder="用户名过滤" className="h-10 w-40 border border-zinc-300 px-3 text-sm" />
                <select value={userRoleFilter} onChange={(event) => setUserRoleFilter(event.target.value)} className="h-10 border border-zinc-300 bg-white px-3 text-sm">
                  <option value="">全部角色</option>
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </select>
                <select value={userPriorityFilter} onChange={(event) => setUserPriorityFilter(event.target.value)} className="h-10 border border-zinc-300 bg-white px-3 text-sm">
                  <option value="">全部优先级</option>
                  {[1, 2, 3, 4, 5].map((priority) => <option key={priority} value={priority}>优先级 {priority}</option>)}
                </select>
                <button onClick={() => { setFilterUsername(''); setUserRoleFilter(''); setUserPriorityFilter(''); }} className="border border-zinc-300 px-3 py-2 text-sm">清空过滤</button>
                <span className="ml-auto text-sm text-zinc-500">共 {filteredUsers.length} 个用户，第 {userPage}/{totalUserPages} 页</span>
              </div>
            )}
            {lastKey && <div className="border border-emerald-300 bg-emerald-50 p-3 font-mono text-sm text-emerald-900 break-all">新密钥：{lastKey}</div>}
            <UsersTable rows={paginatedUsers} canEdit={isAdmin} disableResetKey={autoRegisterEnabled} onUpdate={updateUser} onResetKey={resetKey} onResetPassword={resetPassword} />
            {totalUserPages > 1 && (
              <div className="flex items-center justify-center gap-2 border border-zinc-300 bg-white py-3">
                <button onClick={() => setUserPage(1)} disabled={userPage === 1} className="border border-zinc-300 px-3 py-1 text-sm disabled:cursor-not-allowed disabled:bg-zinc-100">首页</button>
                <button onClick={() => setUserPage((p) => Math.max(1, p - 1))} disabled={userPage === 1} className="border border-zinc-300 px-3 py-1 text-sm disabled:cursor-not-allowed disabled:bg-zinc-100">上一页</button>
                <span className="px-3 text-sm text-zinc-600">第 {userPage} / {totalUserPages} 页</span>
                <button onClick={() => setUserPage((p) => Math.min(totalUserPages, p + 1))} disabled={userPage === totalUserPages} className="border border-zinc-300 px-3 py-1 text-sm disabled:cursor-not-allowed disabled:bg-zinc-100">下一页</button>
                <button onClick={() => setUserPage(totalUserPages)} disabled={userPage === totalUserPages} className="border border-zinc-300 px-3 py-1 text-sm disabled:cursor-not-allowed disabled:bg-zinc-100">末页</button>
              </div>
            )}
          </section>
        )}
        {activeTab === 'password' && (
          <section className="grid gap-3 border border-zinc-300 bg-white p-4 shadow-sm md:grid-cols-2">
            <h3 className="md:col-span-2 font-medium">密码管理</h3>
            <label className="text-sm">原密码
              <input type="password" autoComplete="off" value={oldPassword} onChange={(event) => setOldPassword(event.target.value)} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="请输入原密码" />
            </label>
            <div></div>
            <label className="text-sm">新密码
              <input type="password" autoComplete="off" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="请输入新密码（至少6位）" />
            </label>
            <label className="text-sm">确认新密码
              <input type="password" autoComplete="off" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="请再次输入新密码" />
            </label>
            <div className="md:col-span-2 flex items-center gap-4">
              <button onClick={handleChangePassword} className="w-fit bg-zinc-950 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800">修改密码</button>
              <span className="text-xs text-zinc-500">修改密码后需要重新登录</span>
            </div>
          </section>
        )}

        {activeTab === 'settings' && !isAdmin && <AdminHint />}
        {activeTab === 'settings' && isAdmin && (
          <section className="space-y-4 border border-zinc-300 bg-white p-4 shadow-sm">
            <h2 className="text-lg font-semibold">系统设置</h2>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={autoRegisterEnabled} onChange={(event) => setAutoRegisterEnabled(event.target.checked)} />
              开启自动注册
            </label>
            <section className="grid gap-3 border border-zinc-200 bg-zinc-50 p-3 md:grid-cols-2">
              <h3 className="md:col-span-2 font-medium">时间校准</h3>
              <label className="text-sm">当前系统时间
                <input value={systemTimeMinute} readOnly className="mt-1 h-10 w-full border border-zinc-300 bg-zinc-100 px-3 text-sm" />
              </label>
              <label className="text-sm">校准时间（分钟，可为负数）
                <input type="number" value={timeOffsetMinutes} onChange={(event) => setTimeOffsetMinutes(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <p className="md:col-span-2 text-xs text-zinc-600">写入数据库的用量、对话和监控时间会加上该校准分钟数，保存后动态生效。</p>
            </section>
            <section className="grid gap-3 border border-zinc-200 bg-zinc-50 p-3 md:grid-cols-3">
              <h3 className="md:col-span-3 font-medium">限速设置</h3>
              <label className="text-sm">统计窗口（分钟）
                <input type="number" min={1} value={rateLimitWindowMinutes} onChange={(event) => setRateLimitWindowMinutes(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className="text-sm">窗口内请求次数
                <input type="number" min={0} value={rateLimitRequestThreshold} onChange={(event) => setRateLimitRequestThreshold(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className="text-sm">窗口使用额度
                <input type="number" min={0} step="0.01" value={windowQuotaLimit} onChange={(event) => setWindowQuotaLimit(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className="text-sm">每日使用额度
                <input type="number" min={0} step="0.01" value={dailyQuotaLimit} onChange={(event) => setDailyQuotaLimit(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className={`text-sm${windowQuotaAction === 'reject' && dailyQuotaAction === 'reject' ? ' opacity-50' : ''}`}>降级后优先级
                <select value={rateLimitDowngradedPriority} onChange={(event) => setRateLimitDowngradedPriority(Number(event.target.value))} disabled={windowQuotaAction === 'reject' && dailyQuotaAction === 'reject'} className={`mt-1 h-10 w-full border border-zinc-300 bg-white px-3 text-sm${windowQuotaAction === 'reject' && dailyQuotaAction === 'reject' ? ' cursor-not-allowed bg-zinc-100' : ''}`}>
                  {[1, 2, 3, 4, 5].map((priority) => <option key={priority} value={priority}>{priority}</option>)}
                </select>
              </label>
              <label className="text-sm">窗口超额处理
                <select value={windowQuotaAction} onChange={(event) => setWindowQuotaAction(event.target.value)} className="mt-1 h-10 w-full border border-zinc-300 bg-white px-3 text-sm">
                  <option value="limit">降级优先级</option>
                  <option value="reject">拒绝请求</option>
                </select>
              </label>
              <label className="text-sm">每日超额处理
                <select value={dailyQuotaAction} onChange={(event) => setDailyQuotaAction(event.target.value)} className="mt-1 h-10 w-full border border-zinc-300 bg-white px-3 text-sm">
                  <option value="limit">降级优先级</option>
                  <option value="reject">拒绝请求</option>
                </select>
              </label>
              <p className="md:col-span-3 text-xs text-zinc-600">优先级 1 用户不受限速影响。窗口限速（请求次数/额度）和每日额度可分别设置超额处理方式，均默认降级优先级；每日额度设为拒绝请求时，超限用户将被直接拦截。额度按 total_price 累计，例如每请求 180K 输入 token × 2 请求 = 0.36；每日额度默认 20，约可发送 110 次同类请求。每日额度从凌晨1点起算。</p>
            </section>
            <section className="grid gap-3 border border-zinc-200 bg-zinc-50 p-3 md:grid-cols-3">
              <h3 className="md:col-span-3 font-medium">调度设置</h3>
              <label className="text-sm">高优先级超时（秒）
                <input type="number" min={1} value={timeoutHighPriority} onChange={(event) => setTimeoutHighPriority(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className="text-sm">低优先级超时（秒）
                <input type="number" min={1} value={timeoutLowPriority} onChange={(event) => setTimeoutLowPriority(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className="text-sm">GPU 使用率阈值
                <input type="number" min={0} max={1} step="0.01" value={gpuThreshold} onChange={(event) => setGpuThreshold(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className="text-sm">高低优先级处理比例
                <input type="number" min={1} value={schedulerHighLowRatio} onChange={(event) => setSchedulerHighLowRatio(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className="text-sm">调度循环间隔（秒）
                <input type="number" min={0.01} step="0.01" value={schedulerSleepInterval} onChange={(event) => setSchedulerSleepInterval(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className="text-sm">最小等待请求数
                <input type="number" min={0} value={schedulerMinWaitingRequests} onChange={(event) => setSchedulerMinWaitingRequests(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className="text-sm">高优先级最大未响应数
                <input type="number" min={0} value={schedulerMaxPendingRequests} onChange={(event) => setSchedulerMaxPendingRequests(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className="text-sm">低优先级最大未响应数
                <input type="number" min={0} value={schedulerLowPriorityMaxPending} onChange={(event) => setSchedulerLowPriorityMaxPending(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className="text-sm">默认优先级
                <select value={schedulerDefaultPriority} onChange={(event) => setSchedulerDefaultPriority(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 bg-white px-3 text-sm">
                  {[1, 2, 3, 4, 5].map((priority) => <option key={priority} value={priority}>{priority}</option>)}
                </select>
              </label>
              <label className="text-sm">高优先级最大值
                <select value={schedulerHighPriorityMax} onChange={(event) => setSchedulerHighPriorityMax(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 bg-white px-3 text-sm">
                  {[1, 2, 3, 4, 5].map((priority) => <option key={priority} value={priority}>{priority}</option>)}
                </select>
              </label>
              <label className="text-sm">低优先级最小值
                <select value={schedulerLowPriorityMin} onChange={(event) => setSchedulerLowPriorityMin(Number(event.target.value))} className="mt-1 h-10 w-full border border-zinc-300 bg-white px-3 text-sm">
                  {[1, 2, 3, 4, 5].map((priority) => <option key={priority} value={priority}>{priority}</option>)}
                </select>
              </label>
              <p className="md:col-span-3 text-xs text-zinc-600">保存后网关和调度器会动态读取这些配置，无需直接修改 Python 配置。</p>
            </section>
            <section className="grid gap-3 border border-zinc-200 bg-zinc-50 p-3 md:grid-cols-2">
              <h3 className="md:col-span-2 font-medium">Token 设置</h3>
              <label className="text-sm">tiktoken 本地缓存目录
                <input value={tokenCacheDir} onChange={(event) => setTokenCacheDir(event.target.value)} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
              <label className="text-sm">默认编码模型
                <input value={defaultTokenizerModel} onChange={(event) => setDefaultTokenizerModel(event.target.value)} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
              </label>
            </section>
            <button onClick={saveConfig} className="w-fit bg-zinc-950 px-4 py-2 text-sm font-medium text-white">保存系统配置</button>
          </section>
        )}
      </div>
    </main>
  );
}

function Chart({ title, data, lines, percent = false, mounted, xAxisMode = 'time', yUnit }: { title: string; data: Record<string, unknown>[]; lines: { key: string; name: string; color: string }[]; percent?: boolean; mounted: boolean; xAxisMode?: 'time' | 'date'; yUnit?: string }) {
  const yTickFmt = (value: number) => {
    if (percent) return `${(value * 100).toFixed(0)}%`;
    if (yUnit) return `${value}${yUnit}`;
    return value.toLocaleString();
  };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tooltipFmt = (value: any) => {
    const n = Number(value ?? 0);
    if (percent) return `${(n * 100).toFixed(2)}%`;
    if (yUnit) return `${n}${yUnit}`;
    return n.toLocaleString();
  };
  return (
    <section className="border border-zinc-300 bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-lg font-semibold">{title}</h2>
      <div className="h-[320px] min-h-[320px] w-full min-w-0">
        {mounted && (
        <ResponsiveContainer width="100%" height={320} minWidth={320} minHeight={320}>
          <LineChart data={data} margin={{ top: 5, right: 24, left: 8, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="timestamp" tickFormatter={(value) => xAxisMode === 'date' ? String(value).slice(5, 10) : new Date(String(value)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} />
            <YAxis tickFormatter={yTickFmt} />
            <Tooltip labelFormatter={(label) => xAxisMode === 'date' ? String(label) : new Date(String(label)).toLocaleString()} formatter={tooltipFmt} />
            <Legend />
            {lines.map((line) => <Line key={line.key} type="monotone" dataKey={line.key} name={line.name} stroke={line.color} dot={false} />)}
          </LineChart>
        </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}

function AdminHint() {
  return (
    <section className="border border-zinc-300 bg-white p-5 shadow-sm">
      <h2 className="text-lg font-semibold">需要超级用户权限</h2>
      <p className="mt-2 text-sm text-zinc-600">输入 admin 用户的 API Key 后点击刷新，就可以管理模型配置、用户和系统设置。</p>
    </section>
  );
}

function UsageTable({ rows }: { rows: UsageRow[] }) {
  return (
    <section className="overflow-x-auto border border-zinc-300 bg-white">
      <table className="w-full min-w-[900px] text-left text-sm">
        <thead className="bg-zinc-200 text-zinc-700">
          <tr>
            {['用户', '模型', '输入 token', '输出 token', '总 token', '价格', '当日用量', '请求数'].map((head) => <th key={head} className="px-3 py-2 font-medium">{head}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.user_id}-${row.model_name}-${index}`} className="border-t border-zinc-200">
              <td className="px-3 py-2">{row.username}</td>
              <td className="px-3 py-2">{row.model_name}</td>
              <td className="px-3 py-2">{Number(row.prompt_tokens).toLocaleString()}</td>
              <td className="px-3 py-2">{Number(row.completion_tokens).toLocaleString()}</td>
              <td className="px-3 py-2">{Number(row.total_tokens).toLocaleString()}</td>
              <td className="px-3 py-2">{Number(row.total_price).toFixed(6)}</td>
              <td className="px-3 py-2">{Number(row.daily_price || 0).toFixed(6)}</td>
              <td className="px-3 py-2">{Number(row.request_count).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function ModelDailyChart({ rows, mounted }: { rows: ModelDailyRow[]; mounted: boolean }) {
  const models = useMemo(() => Array.from(new Set(rows.map((row) => row.model_name))).sort(), [rows]);
  const data = useMemo(() => {
    const byDay = new Map<string, Record<string, unknown>>();
    rows.forEach((row) => {
      const day = row.day;
      const item = byDay.get(day) || { timestamp: day };
      item[row.model_name] = Number(row.prompt_tokens);
      byDay.set(day, item);
    });
    return Array.from(byDay.values()).sort((left, right) => String(left.timestamp).localeCompare(String(right.timestamp)));
  }, [rows]);

  return (
    <Chart
      title="最近 30 天输入 Token 数"
      data={data}
      lines={models.map((model, index) => ({ key: model, name: model, color: COLORS[index % COLORS.length] }))}
      mounted={mounted}
      xAxisMode="date"
    />
  );
}

function ConversationList({ rows }: { rows: ConversationRow[] }) {
  return (
    <section className="space-y-3">
      {rows.map((row) => (
        <article key={row.id} className="border border-zinc-300 bg-white p-4">
          <div className="mb-2 flex flex-wrap gap-3 text-xs text-zinc-500">
            <span>{new Date(row.created_at).toLocaleString()}</span>
            <span>{row.username}</span>
            <span>{row.model_name}</span>
            <span>input {Number(row.prompt_tokens).toLocaleString()}</span>
            <span>output {Number(row.completion_tokens).toLocaleString()}</span>
            <span>total {Number(row.total_tokens).toLocaleString()}</span>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap bg-zinc-100 p-3 text-sm">{row.user_prompt}</pre>
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap bg-zinc-100 p-3 text-sm">{row.assistant_response}</pre>
          </div>
        </article>
      ))}
    </section>
  );
}

function GPUMonitor({ servers }: { servers: GPUServerData }) {
  const serverEntries = Object.entries(servers);

  if (serverEntries.length === 0) {
    return (
      <section className="border border-zinc-300 bg-white p-6 text-center shadow-sm">
        <p className="text-zinc-500">暂无 GPU 服务器数据</p>
      </section>
    );
  }

  return (
    <section className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {serverEntries.map(([ip, data]) => {
        const gpus = Array.isArray(data) ? data : null;
        const error = typeof data === 'string' ? data : null;
        const isOnline = gpus !== null;

        return (
          <div key={ip} className="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm">
            <div className="mb-3 flex items-center justify-between">
              <span className="font-medium text-zinc-800">{ip}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${isOnline ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>
                {isOnline ? '在线' : '离线'}
              </span>
            </div>

            {error && (
              <p className="text-sm text-red-600">{error}</p>
            )}

            {gpus && (
              <div className="space-y-3">
                {gpus.map((gpu) => (
                  <div key={gpu.index} className="rounded-md border border-zinc-100 bg-zinc-50 p-3">
                    <div className="mb-2 flex items-center justify-between text-sm">
                      <span className="font-medium text-zinc-700">GPU {gpu.index}: {gpu.model}</span>
                      <span className="text-zinc-500">{gpu.memory_used_percent.toFixed(1)}%</span>
                    </div>
                    <div className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-200">
                      <div
                        className="h-full rounded-full transition-all duration-300"
                        style={{
                          width: `${gpu.memory_used_percent}%`,
                          backgroundColor: gpu.memory_used_percent > 90 ? '#dc2626' : gpu.memory_used_percent > 70 ? '#f59e0b' : '#22c55e',
                        }}
                      />
                    </div>
                    <div className="mt-1.5 flex justify-between text-xs text-zinc-500">
                      <span>已用: {(gpu.memory_used_mb / 1024).toFixed(1)} GB</span>
                      <span>总计: {(gpu.memory_total_mb / 1024).toFixed(1)} GB</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}

function ModelModal({
  editingModel,
  modelName,
  modelForm,
  modelType,
  modelQueues,
  onClose,
  onSave,
  onModelNameChange,
  onModelFormChange,
  onModelTypeChange,
  onQueueChange,
  onQueueAdd,
  onQueueRemove,
}: {
  editingModel: string;
  modelName: string;
  modelForm: typeof emptyModelForm;
  modelType: ModelType;
  modelQueues: ModelQueueConfig[];
  onClose: () => void;
  onSave: () => Promise<void>;
  onModelNameChange: (value: string) => void;
  onModelFormChange: (value: typeof emptyModelForm) => void;
  onModelTypeChange: (value: ModelType) => void;
  onQueueChange: (index: number, patch: Partial<ModelQueueConfig>) => void;
  onQueueAdd: () => void;
  onQueueRemove: (index: number) => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/45 px-4 py-8">
      <section className="w-full max-w-5xl border border-zinc-300 bg-white shadow-xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-zinc-300 bg-white px-5 py-4">
          <h2 className="text-lg font-semibold">{editingModel ? `编辑模型：${editingModel}` : '新增模型'}</h2>
          <button onClick={onClose} className="border border-zinc-300 px-3 py-1 text-sm">关闭</button>
        </div>
        <div className="grid gap-4 p-5">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-sm">网关模型名称
              <input value={modelName} onChange={(event) => onModelNameChange(event.target.value)} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="deepseek" />
            </label>
            <label className="text-sm">模型类型
              <select value={modelType} onChange={(event) => onModelTypeChange(event.target.value as ModelType)} className="mt-1 h-10 w-full border border-zinc-300 bg-white px-3 text-sm">
                <option value="single">单队列模型</option>
                <option value="multi-queue">多队列模型</option>
              </select>
            </label>
            <label className="text-sm">下游 API Key
              <input value={modelForm.api_key} onChange={(event) => onModelFormChange({ ...modelForm, api_key: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="模型级默认 Key，可被队列 Key 覆盖" />
            </label>
            <label className="text-sm">tiktoken 编码模型
              <input value={modelForm.tokenizer_model} onChange={(event) => onModelFormChange({ ...modelForm, tokenizer_model: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="gpt-3.5-turbo" />
            </label>
          </div>

          {modelType === 'single' && (
            <div className="grid gap-3 border border-zinc-200 bg-zinc-50 p-3 md:grid-cols-3">
              <label className="text-sm">下游 API URL
                <input value={modelForm.api_url} onChange={(event) => onModelFormChange({ ...modelForm, api_url: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="https://api.example.com" />
              </label>
              <label className="text-sm">下游模型名称
                <input value={modelForm.model_name} onChange={(event) => onModelFormChange({ ...modelForm, model_name: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="deepseek-v4-flash" />
              </label>
              <label className="text-sm">队列名称
                <input value={modelForm.queue_name} onChange={(event) => onModelFormChange({ ...modelForm, queue_name: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="deepseek" />
              </label>
            </div>
          )}

          {modelType === 'multi-queue' && (
            <section className="space-y-3 border border-zinc-200 bg-zinc-50 p-3">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <label className="min-w-72 flex-1 text-sm">负载索引队列 load_queue
                  <input value={modelForm.load_queue} onChange={(event) => onModelFormChange({ ...modelForm, load_queue: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder={`${modelName || 'model'}-load-queue`} />
                </label>
                <button onClick={onQueueAdd} className="h-10 border border-zinc-950 bg-white px-3 text-sm">添加队列</button>
              </div>
              <div className="space-y-3">
                {modelQueues.map((queue, index) => (
                  <div key={index} className="grid gap-2 border border-zinc-300 bg-white p-3 lg:grid-cols-[1fr_1.2fr_1fr_1fr_0.7fr_auto]">
                    <label className="text-xs text-zinc-600">队列名称
                      <input value={queue.queue_name || ''} onChange={(event) => onQueueChange(index, { queue_name: event.target.value })} className="mt-1 h-9 w-full border border-zinc-300 px-2 text-sm" placeholder="testname-coder1" />
                    </label>
                    <label className="text-xs text-zinc-600">API URL
                      <input value={queue.api_url || ''} onChange={(event) => onQueueChange(index, { api_url: event.target.value })} className="mt-1 h-9 w-full border border-zinc-300 px-2 text-sm" placeholder="http://host:port" />
                    </label>
                    <label className="text-xs text-zinc-600">下游模型
                      <input value={queue.model_name || ''} onChange={(event) => onQueueChange(index, { model_name: event.target.value })} className="mt-1 h-9 w-full border border-zinc-300 px-2 text-sm" placeholder="minimax2.7" />
                    </label>
                    <label className="text-xs text-zinc-600">队列 API Key
                      <input value={queue.api_key || ''} onChange={(event) => onQueueChange(index, { api_key: event.target.value })} className="mt-1 h-9 w-full border border-zinc-300 px-2 text-sm" placeholder="可选" />
                    </label>
                    <label className="text-xs text-zinc-600">负载倍率
                      <input type="number" min={0.1} step="0.1" value={queue.load_factor ?? 1} onChange={(event) => onQueueChange(index, { load_factor: Number(event.target.value) })} className="mt-1 h-9 w-full border border-zinc-300 px-2 text-sm" />
                    </label>
                    <div className="flex items-end">
                      <button onClick={() => onQueueRemove(index)} disabled={modelQueues.length <= 1} className="h-9 border border-red-300 px-3 text-sm text-red-700 disabled:cursor-not-allowed disabled:bg-zinc-100 disabled:text-zinc-400">删除</button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          <div className="grid gap-3 md:grid-cols-4">
            <label className="text-sm">输入价/1K
              <input type="number" min={0} step="0.000001" value={modelForm.input_per_1k} onChange={(event) => onModelFormChange({ ...modelForm, input_per_1k: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
            </label>
            <label className="text-sm">输出价/1K
              <input type="number" min={0} step="0.000001" value={modelForm.output_per_1k} onChange={(event) => onModelFormChange({ ...modelForm, output_per_1k: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
            </label>
            <label className="text-sm">币种
              <input value={modelForm.currency} onChange={(event) => onModelFormChange({ ...modelForm, currency: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" />
            </label>
            <label className="flex items-center gap-2 pt-6 text-sm">
              <input type="checkbox" checked={modelForm.enabled} onChange={(event) => onModelFormChange({ ...modelForm, enabled: event.target.checked })} />
              启用模型
            </label>
          </div>

          <section className="space-y-3 border border-zinc-200 bg-zinc-50 p-3">
            <h3 className="text-sm font-semibold text-zinc-700">时间段倍率设置</h3>
            <div className="grid gap-3 md:grid-cols-4">
              <label className="text-sm">工作日高峰 (9:00-18:00)
                <input type="number" min={0} step="0.1" value={modelForm.weekday_peak} onChange={(event) => onModelFormChange({ ...modelForm, weekday_peak: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="1.5" />
              </label>
              <label className="text-sm">工作日平峰 (18:00-23:00)
                <input type="number" min={0} step="0.1" value={modelForm.weekday_flat} onChange={(event) => onModelFormChange({ ...modelForm, weekday_flat: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="1.0" />
              </label>
              <label className="text-sm">夜间 (23:00-9:00)
                <input type="number" min={0} step="0.1" value={modelForm.night} onChange={(event) => onModelFormChange({ ...modelForm, night: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="0.3" />
              </label>
              <label className="text-sm">周末 (周六周日)
                <input type="number" min={0} step="0.1" value={modelForm.weekend} onChange={(event) => onModelFormChange({ ...modelForm, weekend: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="0.3" />
              </label>
            </div>
          </section>

          <section className="space-y-3 border border-zinc-200 bg-zinc-50 p-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-zinc-700">降质模型 API 设置</h3>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={modelForm.degrade_enabled} onChange={(event) => onModelFormChange({ ...modelForm, degrade_enabled: event.target.checked })} />
                启用降质
              </label>
            </div>
            {modelForm.degrade_enabled && (
              <div className="space-y-3">
                <div className="grid gap-3 md:grid-cols-3">
                  <label className="text-sm">降质 API URL
                    <input value={modelForm.degrade_api_url} onChange={(event) => onModelFormChange({ ...modelForm, degrade_api_url: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="https://api.fallback.com" />
                  </label>
                  <label className="text-sm">降质模型名称
                    <input value={modelForm.degrade_model_name} onChange={(event) => onModelFormChange({ ...modelForm, degrade_model_name: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="gpt-3.5-turbo" />
                  </label>
                  <label className="text-sm">降质 API Key
                    <input value={modelForm.degrade_api_key} onChange={(event) => onModelFormChange({ ...modelForm, degrade_api_key: event.target.value })} className="mt-1 h-10 w-full border border-zinc-300 px-3 text-sm" placeholder="可选" />
                  </label>
                </div>
                {(() => {
                  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || '';
                  const degradeUrl = modelForm.degrade_api_url.trim();
                  const isLocalGateway = degradeUrl && (
                    degradeUrl === apiBaseUrl ||
                    degradeUrl.replace(/\/$/, '') === apiBaseUrl.replace(/\/$/, '') ||
                    degradeUrl.startsWith('http://localhost:') ||
                    degradeUrl.startsWith('http://127.0.0.1:')
                  );
                  const hasApiKey = modelForm.degrade_api_key.trim().length > 0;

                  if (isLocalGateway && hasApiKey) {
                    return (
                      <div className="rounded bg-amber-50 border border-amber-300 px-3 py-2 text-xs text-amber-900">
                        <strong>⚠️ 警告：</strong>降质 API URL 指向本网关，建议清空降质 API Key 以透传原始用户的 API Key，这样降质请求将以原用户身份记录。
                      </div>
                    );
                  } else if (isLocalGateway && !hasApiKey) {
                    return (
                      <div className="rounded bg-green-50 border border-green-300 px-3 py-2 text-xs text-green-800">
                        <strong>✓ 正确：</strong>降质 API URL 指向本网关且未设置降质 API Key，系统将自动透传原始用户的 API Key。
                      </div>
                    );
                  } else if (!isLocalGateway && !hasApiKey) {
                    return (
                      <div className="rounded bg-amber-50 border border-amber-300 px-3 py-2 text-xs text-amber-900">
                        <strong>⚠️ 警告：</strong>降质 API URL 指向外部服务，但未设置降质 API Key，请求可能失败。
                      </div>
                    );
                  } else {
                    return (
                      <div className="rounded bg-blue-50 border border-blue-200 px-3 py-2 text-xs text-blue-800">
                        <strong>提示：</strong>降质 API URL 指向外部服务，将使用配置的降质 API Key 进行请求。
                      </div>
                    );
                  }
                })()}
              </div>
            )}
          </section>
        </div>
        <div className="sticky bottom-0 flex justify-end gap-2 border-t border-zinc-300 bg-white px-5 py-4">
          <button onClick={onClose} className="border border-zinc-300 px-4 py-2 text-sm">取消</button>
          <button onClick={onSave} className="bg-zinc-950 px-4 py-2 text-sm font-medium text-white">保存模型配置</button>
        </div>
      </section>
    </div>
  );
}

function ModelTable({ rows, onEdit, onDelete }: { rows: Record<string, ModelConfig>; onEdit: (name: string, config: ModelConfig) => void; onDelete: (name: string) => Promise<void> }) {
  const entries = Object.entries(rows);
  return (
    <section className="overflow-x-auto border border-zinc-300 bg-white shadow-sm">
      <table className="w-full min-w-[980px] text-left text-sm">
        <thead className="bg-zinc-200 text-zinc-700">
          <tr>
            {['模型', '类型', '下游模型', 'API URL', '队列', '启用', '输入价/1K', '输出价/1K', '币种', '操作'].map((head) => <th key={head} className="px-3 py-2 font-medium">{head}</th>)}
          </tr>
        </thead>
        <tbody>
          {entries.map(([name, config]) => (
            <tr key={name} className="border-t border-zinc-200">
              <td className="px-3 py-2 font-medium">{name}</td>
              <td className="px-3 py-2">{config.type || 'single'}</td>
              <td className="px-3 py-2">{config.model_name || config.queues?.[0]?.model_name || '-'}</td>
              <td className="max-w-60 truncate px-3 py-2" title={config.api_url || config.queues?.[0]?.api_url || ''}>{config.api_url || config.queues?.[0]?.api_url || '-'}</td>
              <td className="px-3 py-2">{config.type === 'multi-queue' ? `${config.queues?.length || 0} 个队列` : (config.queue_name || '-')}</td>
              <td className="px-3 py-2">{config.enabled ?? true ? '是' : '否'}</td>
              <td className="px-3 py-2">{Number(config.price?.input_per_1k ?? 0).toFixed(6)}</td>
              <td className="px-3 py-2">{Number(config.price?.output_per_1k ?? 0).toFixed(6)}</td>
              <td className="px-3 py-2">{config.price?.currency || '-'}</td>
              <td className="px-3 py-2">
                <div className="flex gap-2">
                  <button onClick={() => onEdit(name, config)} className="border border-zinc-300 px-3 py-1">编辑</button>
                  <button onClick={() => onDelete(name)} className="border border-red-300 px-3 py-1 text-red-700">删除</button>
                </div>
              </td>
            </tr>
          ))}
          {entries.length === 0 && (
            <tr>
              <td colSpan={10} className="px-3 py-8 text-center text-zinc-500">暂无模型配置</td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}

function UsersTable({ rows, canEdit, disableResetKey, onUpdate, onResetKey, onResetPassword }: { rows: UserRow[]; canEdit: boolean; disableResetKey: boolean; onUpdate: (user: UserRow, patch: Partial<UserRow>) => Promise<void>; onResetKey: (user: UserRow) => Promise<void>; onResetPassword: (user: UserRow) => Promise<void> }) {
  return (
    <section className="overflow-x-auto border border-zinc-300 bg-white">
      <table className="w-full min-w-[1240px] text-left text-sm">
        <thead className="bg-zinc-200 text-zinc-700">
          <tr>
            {['ID', '用户名', '角色', '优先级', '无限额度', '额度上限', '已用额度', '启用', '自动注册', '操作'].map((head) => <th key={head} className="px-3 py-2 font-medium">{head}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((user) => (
            <tr key={user.id} className="border-t border-zinc-200">
              <td className="px-3 py-2">{user.id}</td>
              <td className="px-3 py-2">{user.username}</td>
              <td className="px-3 py-2">
                <select value={user.role} disabled={!canEdit} onChange={(event) => onUpdate(user, { role: event.target.value })} className="border border-zinc-300 bg-white px-2 py-1 disabled:bg-zinc-100 disabled:text-zinc-500">
                  <option value="user">user</option>
                  <option value="admin">admin</option>
                </select>
              </td>
              <td className="px-3 py-2">
                <select value={user.priority ?? 3} disabled={!canEdit} onChange={(event) => onUpdate(user, { priority: Number(event.target.value) })} className="border border-zinc-300 bg-white px-2 py-1 disabled:bg-zinc-100 disabled:text-zinc-500">
                  {[1, 2, 3, 4, 5].map((priority) => <option key={priority} value={priority}>{priority}</option>)}
                </select>
              </td>
              <td className="px-3 py-2"><input type="checkbox" disabled={!canEdit} checked={user.quota_unlimited} onChange={(event) => onUpdate(user, { quota_unlimited: event.target.checked })} /></td>
              <td className="px-3 py-2">
                <input
                  key={`${user.id}-${user.quota_unlimited}-${user.quota_limit ?? 'none'}`}
                  type="number"
                  min={0}
                  step="0.000001"
                  disabled={!canEdit || user.quota_unlimited}
                  defaultValue={user.quota_limit ?? ''}
                  onBlur={(event) => onUpdate(user, { quota_limit: event.target.value === '' ? null : Number(event.target.value) })}
                  className="h-8 w-32 border border-zinc-300 px-2 disabled:bg-zinc-100 disabled:text-zinc-500"
                  placeholder={user.quota_unlimited ? '无限' : '额度'}
                />
              </td>
              <td className="px-3 py-2">{Number(user.quota_used).toFixed(6)}</td>
              <td className="px-3 py-2"><input type="checkbox" disabled={!canEdit} checked={user.enabled} onChange={(event) => onUpdate(user, { enabled: event.target.checked })} /></td>
              <td className="px-3 py-2">{user.auto_registered ? '是' : '否'}</td>
              <td className="px-3 py-2">
                <div className="flex gap-2">
                  <button disabled={disableResetKey} onClick={() => onResetKey(user)} className="border border-zinc-300 px-3 py-1 disabled:cursor-not-allowed disabled:bg-zinc-100 disabled:text-zinc-400">
                    重置密钥
                  </button>
                  {canEdit && (
                    <button onClick={() => onResetPassword(user)} className="border border-zinc-300 px-3 py-1 hover:bg-zinc-50">
                      重置密码
                    </button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
