# Next.js 静态文件生成与 Nginx 部署指南

## 1. 生成静态文件

### 1.1 配置 Next.js

确保 `next.config.ts` 文件包含以下配置：

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 启用静态导出
  output: 'export',
  // 仅在生产环境中设置基础路径
  ...(process.env.NODE_ENV === 'production' ? { basePath: '/llm-monitor' } : {}),
};

export default nextConfig;
```

### 1.2 构建静态文件

在项目根目录运行以下命令：

```bash
cd frontend
# 开发环境
npm run dev

# 生产环境构建（必须设置 NODE_ENV=production）
NODE_ENV=production npm run build
```

注意：为了使 basePath 配置生效，构建静态文件时必须设置 `NODE_ENV=production` 环境变量。

构建完成后，静态文件将生成在 `out` 目录中。

## 2. Nginx 配置

### 2.1 配置文件修改

在 `/etc/nginx/nginx.conf` 中添加以下 server 块：

```nginx
server {
    listen 7013;
    server_name localhost;

    # LLM调度系统监控面板
    location /llm-monitor {
        alias /data01/tsn/code_test/LLM_Scheduling/frontend/out;
        index index.html;
        try_files $uri $uri/ /llm-monitor/index.html;
    }

    # 其他路径配置
    location / {
        root /data01/tsn/deploy/log_analysis_source_data/html_tem;
        index generated_page.html;
        try_files $uri $uri/ /generated_page.html;
    }
}
```

### 2.2 关键配置说明

- `listen 7013;` - 监听端口
- `location /llm-monitor` - 为监控面板设置路径
- `alias` - 指向静态文件目录（out 目录的完整路径）
- `try_files` - 处理 SPA 路由，确保所有路径都返回 index.html

### 2.3 路径变更说明

如果将 `out` 目录移动到其他位置，需同步修改 nginx 配置中 `alias` 的路径。

使用 `alias` 指令时，location 路径会被完全替换为 alias 指定的路径，因此配置 alias 为 `.../frontend/out` 后，访问 `/llm-monitor/` 会直接映射到 `frontend/out/` 目录。

## 3. 部署步骤

1. 构建 Next.js 应用：

   ```bash
   cd frontend
   NODE_ENV=production npm run build
   ```
2. 测试 Nginx 配置：

   ```bash
   sudo nginx -t
   ```
3. 重新加载 Nginx 配置：

   ```bash
   sudo nginx -s reload
   ```
4. 访问应用：
   打开浏览器访问 `http://localhost:7013/llm-monitor`

## 4. 常见问题

标签栏图标：将favicon.ico 放到app目录下就行。 frontend\src\app\favicon.ico ，
