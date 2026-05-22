# LLM 调度网关前端

这是一个基于 [Next.js](https://nextjs.org) 的项目。

## 快速开始

首先，启动开发服务器：

```bash
npm run dev
```

在浏览器中打开 [http://localhost:3000](http://localhost:3000) 查看结果。

可以通过修改 `app/page.tsx` 来编辑页面，页面会自动更新。

## 依赖管理

### 临时删除 node_modules

如果需要节省磁盘空间或加速某些操作，可以临时删除 `node_modules` 目录：

```bash
rm -rf frontend/node_modules
```

### 恢复 node_modules

需要恢复依赖时，运行以下命令：

```bash
cd frontend
npm install
```

`npm install` 会根据 `package.json` 和 `package-lock.json` 自动重新安装所有依赖，确保安装相同版本的依赖。

## 生产部署

生产环境不要使用 `npm run dev`，应先构建再用生产服务启动。

本项目使用 Next.js 生产服务部署，`next.config.ts` 不应配置 `output: 'export'`。如果配置了静态导出，`next start` 会报错，应删除该配置并重新构建。

### 1. 配置后端地址

前端需要能跨服务器访问后端，所以 `NEXT_PUBLIC_API_BASE_URL` 不能写成只在本机可用的地址。把它设置为浏览器可访问的后端地址：

```bash
cd /home/tsn/github_code/LLM_Scheduling/frontend
cat > .env.production <<'EOF'
NEXT_PUBLIC_API_BASE_URL=http://后端服务器IP:7103
EOF
```

如果前端和后端不在同一台服务器，也必须使用后端服务器的真实 IP 或域名，例如：

```bash
NEXT_PUBLIC_API_BASE_URL=http://10.45.155.210:7103
```

### 2. 安装依赖并构建

```bash
cd /home/tsn/github_code/LLM_Scheduling/frontend
npm install
npm run build
```

注意：`NEXT_PUBLIC_API_BASE_URL` 是构建时注入的，修改后端地址后需要重新执行 `npm run build`。

### 3. 启动前端生产服务

启动脚本会先杀掉原来的前端生产进程，再启动新的服务，并通过 `next start -H 0.0.0.0` 监听所有网卡，支持其它机器访问。

```bash
cd /home/tsn/github_code/LLM_Scheduling/frontend
chmod +x start.sh stop.sh
./start.sh
```

默认端口是 `3000`，访问地址：

```text
http://前端服务器IP:3000
```

指定端口：

```bash
PORT=3001 ./start.sh
```

### 4. 停止前端生产服务

```bash
cd /home/tsn/github_code/LLM_Scheduling/frontend
./stop.sh
```

如果启动时指定了端口，停止时也要指定同一个端口：

```bash
PORT=3001 ./stop.sh
```

更多部署说明可参考 `frontend/DEPLOYMENT_GUIDE.md`。
