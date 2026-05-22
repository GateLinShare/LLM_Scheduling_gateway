import asyncio
import asyncpg
import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Dict
from config import *
import runtime_config
import pandas as pd

# ## 使用方法
# ### 1. 安装依赖
# pip install asyncpg

# ### 2. 导入模块
# import asyncio
# from db_module import write_model_usage

# ### 3. 记录模型使用日志
# 在需要记录模型使用的地方调用写入函数：
# # 不等待写入完成，避免影响性能
# asyncio.create_task(
#     write_model_usage(
#         service_name="sai_nobackground-image",
#         model_name="RMBG",
#         count=1
#     )
# )

# 数据库连接配置
DB_HOST = DB_CONFIG["host"]
DB_PORT = DB_CONFIG["port"]
DB_NAME = DB_CONFIG["database"]
DB_USER = DB_CONFIG["user"]
DB_PASSWORD = DB_CONFIG["password"]

# 全局连接对象
_db_pool: Optional[asyncpg.Pool] = None

# 重连锁，避免重复连接
_reconnect_lock = asyncio.Lock()
_is_reconnecting = False


def adjusted_now() -> datetime:
    return datetime.now() + timedelta(minutes=runtime_config.time_offset_minutes())

async def _reconnect_database() -> bool:
    """
    重新连接数据库，使用锁机制避免重复连接
    
    Returns:
        bool: 重连是否成功
    """
    global _db_pool, _is_reconnecting
    
    # 如果正在重连，则直接返回失败，避免阻塞
    if _is_reconnecting:
        return False
    
    # 获取重连锁
    async with _reconnect_lock:
        # 如果存在旧的连接池，先关闭它
        if _db_pool:
            await _db_pool.close()
            _db_pool = None
            
        _is_reconnecting = True
        try:
            _db_pool = await asyncpg.create_pool(
                host=DB_HOST,
                port=DB_PORT,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD,
                min_size=1,
                max_size=10,
                command_timeout=60,
            )
            
            # 创建表
            await _create_table_if_not_exists()
            await _create_scheduler_table_if_not_exists()
            await _create_gateway_tables_if_not_exists()
            
            return True
        except Exception:
            _db_pool = None
            return False
        finally:
            _is_reconnecting = False

async def _create_table_if_not_exists():
    """
    创建数据表 api_models_use_log（如果不存在）
    """
    global _db_pool
    
    if not _db_pool:
        raise Exception("数据库未连接")
    
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS api_models_use_log (
        id SERIAL PRIMARY KEY,
        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
        service_name VARCHAR(255) NOT NULL,
        model_name VARCHAR(255) NOT NULL,
        count INTEGER NOT NULL DEFAULT 1,
        ip_address VARCHAR(255),
        content_length INTEGER
    );
    """
    
    async with _db_pool.acquire() as connection:
        await connection.execute(create_table_sql)

async def _create_scheduler_table_if_not_exists():
    """
    创建数据表 llm_gateway_scheduler_monitor_log（如果不存在），用于存储调度器监控数据
    """
    global _db_pool
    
    if not _db_pool:
        raise Exception("数据库未连接")
    
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS llm_gateway_scheduler_monitor_log (
        id SERIAL PRIMARY KEY,
        timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
        model_name VARCHAR(255) NOT NULL,
        gpu_usage NUMERIC(5,2) NOT NULL,
        num_requests_waiting INTEGER NOT NULL,
        pending_requests INTEGER NOT NULL,
        low_priority_pending_requests INTEGER NOT NULL,
        num_requests_running INTEGER NOT NULL,
        queue_length INTEGER NOT NULL
    );
    """
    
    async with _db_pool.acquire() as connection:
        await connection.execute(create_table_sql)

async def _create_gateway_tables_if_not_exists():
    """创建用户、用量、对话和配置审计表。"""
    global _db_pool

    if not _db_pool:
        raise Exception("数据库未连接")

    sql = """
    CREATE TABLE IF NOT EXISTS gateway_users (
        id BIGSERIAL PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        api_key TEXT NOT NULL UNIQUE,
        password_hash TEXT,
        role TEXT NOT NULL CHECK (role IN ('user', 'admin')),
        priority INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
        quota_unlimited BOOLEAN NOT NULL DEFAULT FALSE,
        quota_limit NUMERIC(18,6),
        quota_used NUMERIC(18,6) NOT NULL DEFAULT 0,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,
        auto_registered BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );

    CREATE TABLE IF NOT EXISTS gateway_usage_logs (
        id BIGSERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        user_id BIGINT REFERENCES gateway_users(id),
        username TEXT NOT NULL,
        ip_address INET,
        request_id TEXT NOT NULL,
        model_name TEXT NOT NULL,
        upstream_model_name TEXT,
        service_name TEXT,
        prompt_tokens INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0,
        total_tokens INTEGER NOT NULL DEFAULT 0,
        input_price NUMERIC(18,8) NOT NULL DEFAULT 0,
        output_price NUMERIC(18,8) NOT NULL DEFAULT 0,
        total_price NUMERIC(18,8) NOT NULL DEFAULT 0,
        currency TEXT NOT NULL DEFAULT 'CNY',
        stream BOOLEAN NOT NULL DEFAULT FALSE,
        status_code INTEGER,
        latency_ms INTEGER,
        success BOOLEAN NOT NULL DEFAULT TRUE
    );

    CREATE INDEX IF NOT EXISTS idx_gateway_usage_logs_created_at
      ON gateway_usage_logs(created_at);
    CREATE INDEX IF NOT EXISTS idx_gateway_usage_logs_user_time
      ON gateway_usage_logs(user_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_gateway_usage_logs_model_time
      ON gateway_usage_logs(model_name, created_at DESC);

    CREATE TABLE IF NOT EXISTS gateway_conversation_logs (
        id BIGSERIAL PRIMARY KEY,
        usage_log_id BIGINT REFERENCES gateway_usage_logs(id),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        user_id BIGINT REFERENCES gateway_users(id),
        username TEXT NOT NULL,
        request_id TEXT NOT NULL,
        model_name TEXT NOT NULL,
        user_prompt TEXT,
        assistant_response TEXT,
        prompt_truncated BOOLEAN NOT NULL DEFAULT FALSE,
        response_truncated BOOLEAN NOT NULL DEFAULT FALSE
    );

    CREATE INDEX IF NOT EXISTS idx_gateway_conversation_user_time
      ON gateway_conversation_logs(user_id, created_at DESC);

    CREATE TABLE IF NOT EXISTS gateway_config_audit (
        id BIGSERIAL PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        user_id BIGINT REFERENCES gateway_users(id),
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        config_key TEXT NOT NULL,
        old_value JSONB,
        new_value JSONB
    );
    """

    async with _db_pool.acquire() as connection:
        await connection.execute(sql)
        await connection.execute(
            "ALTER TABLE gateway_users ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 3"
        )
        await connection.execute(
            "ALTER TABLE gateway_users ADD COLUMN IF NOT EXISTS password_hash TEXT"
        )
        await connection.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'gateway_users_priority_check'
                ) THEN
                    ALTER TABLE gateway_users
                    ADD CONSTRAINT gateway_users_priority_check CHECK (priority BETWEEN 1 AND 5);
                END IF;
            END $$;
            """
        )


async def ensure_database():
    if not _db_pool:
        await _reconnect_database()
    return _db_pool is not None


async def create_or_update_initial_admin(username: str, api_key: str):
    if not username or not api_key:
        return None
    if not await ensure_database():
        return None
    # Set default password to INITIAL_ADMIN_PASSWORD (default: "admin")
    password_hash = hash_password(INITIAL_ADMIN_PASSWORD)
    sql = """
    INSERT INTO gateway_users (username, api_key, password_hash, role, priority, quota_unlimited, enabled)
    VALUES ($1, $2, $3, 'admin', 1, true, true)
    ON CONFLICT (username) DO UPDATE SET
      api_key = EXCLUDED.api_key,
      password_hash = EXCLUDED.password_hash,
      role = 'admin',
      priority = COALESCE(gateway_users.priority, 1),
      quota_unlimited = true,
      enabled = true,
      updated_at = now()
    RETURNING *;
    """
    async with _db_pool.acquire() as connection:
        return dict(await connection.fetchrow(sql, username, api_key, password_hash))


async def get_user_by_api_key(api_key: str):
    if not api_key or not await ensure_database():
        return None
    async with _db_pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT * FROM gateway_users WHERE api_key = $1 AND enabled = true",
            api_key,
        )
        return dict(row) if row else None


async def count_user_requests_since(user_id: int, cutoff_time: datetime) -> int:
    if not user_id or not await ensure_database():
        return 0
    async with _db_pool.acquire() as connection:
        value = await connection.fetchval(
            "SELECT COUNT(*) FROM gateway_usage_logs WHERE user_id = $1 AND created_at >= $2",
            user_id,
            cutoff_time,
        )
        return int(value or 0)


async def check_user_quota_limits(user_id: int, cutoff_time: datetime, day_start: datetime) -> dict:
    """Combined query: check daily total_price and window total_price in one SQL"""
    if not user_id or not await ensure_database():
        return {"daily_price": 0.0, "window_price": 0.0}
    day_boundary_expr = "((created_at AT TIME ZONE 'Asia/Shanghai') - interval '1 hour')::date"
    today_boundary = (adjusted_now() - timedelta(hours=1)).date()
    earliest = min(cutoff_time, day_start)
    async with _db_pool.acquire() as connection:
        row = await connection.fetchrow(
            f"""SELECT COALESCE(SUM(CASE WHEN {day_boundary_expr} >= $3 THEN total_price ELSE 0 END), 0)::NUMERIC(18,8) AS daily_price,
                      COALESCE(SUM(CASE WHEN created_at >= $2 THEN total_price ELSE 0 END), 0)::NUMERIC(18,8) AS window_price
               FROM gateway_usage_logs WHERE user_id = $1 AND created_at >= $4""",
            user_id,
            cutoff_time,
            today_boundary,
            earliest,
        )
        return {"daily_price": float(row["daily_price"] or 0), "window_price": float(row["window_price"] or 0)}


async def record_request_for_rate_limit(
    user_id: int,
    username: str,
    ip_address: str,
    request_id: str,
    model_name: str,
) -> int | None:
    """
    Immediately record a minimal request entry for rate limiting purposes.
    Returns the usage_log_id for later update with full details.
    """
    if not await ensure_database():
        return None
    async with _db_pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            INSERT INTO gateway_usage_logs (
                created_at, user_id, username, ip_address, request_id, model_name,
                prompt_tokens, completion_tokens, total_tokens,
                input_price, output_price, total_price, currency, stream, success
            ) VALUES ($1,$2,$3,$4,$5,$6,0,0,0,0,0,0,'CNY',false,false)
            RETURNING id;
            """,
            adjusted_now(), user_id, username, ip_address, request_id, model_name,
        )
        return row["id"] if row else None


async def get_or_create_ip_user(username: str, api_key: str):
    if not await ensure_database():
        return None
    sql = """
    INSERT INTO gateway_users (username, api_key, role, priority, quota_unlimited, enabled, auto_registered)
    VALUES ($1, $2, 'user', 3, true, true, true)
    ON CONFLICT (username) DO UPDATE SET
      api_key = EXCLUDED.api_key,
      updated_at = now()
    RETURNING *;
    """
    async with _db_pool.acquire() as connection:
        row = await connection.fetchrow(sql, username, api_key)
        return dict(row) if row else None


async def list_users():
    if not await ensure_database():
        return []
    async with _db_pool.acquire() as connection:
        rows = await connection.fetch(
            """SELECT id, username, role, priority, quota_unlimited, quota_limit, quota_used,
                      enabled, auto_registered, created_at, updated_at
               FROM gateway_users ORDER BY id"""
        )
        return [dict(row) for row in rows]


async def create_user(username: str, api_key: str, role: str = "user", quota_unlimited: bool = False, quota_limit=None, priority: int = 3):
    if not await ensure_database():
        return None
    # Set default password to 123456 for new users
    password_hash = hash_password("123456")
    sql = """
    INSERT INTO gateway_users (username, api_key, password_hash, role, priority, quota_unlimited, quota_limit, enabled)
    VALUES ($1, $2, $3, $4, $5, $6, $7, true)
    RETURNING *;
    """
    async with _db_pool.acquire() as connection:
        row = await connection.fetchrow(sql, username, api_key, password_hash, role, _normalize_priority(priority), quota_unlimited, quota_limit)
        return dict(row) if row else None


async def update_user(user_id: int, data: dict):
    if not await ensure_database():
        return None
    if "priority" in data:
        data["priority"] = _normalize_priority(data["priority"])
    allowed = {"role", "priority", "quota_unlimited", "quota_limit", "enabled"}
    updates = [(k, v) for k, v in data.items() if k in allowed]
    if not updates:
        return None
    set_sql = ", ".join(f"{key} = ${idx + 2}" for idx, (key, _) in enumerate(updates))
    values = [user_id] + [value for _, value in updates]
    sql = f"UPDATE gateway_users SET {set_sql}, updated_at = now() WHERE id = $1 RETURNING *"
    async with _db_pool.acquire() as connection:
        row = await connection.fetchrow(sql, *values)
        return dict(row) if row else None


def _normalize_priority(priority) -> int:
    try:
        value = int(priority)
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, value))


def hash_password(password: str) -> str:
    """Hash password using bcrypt with salt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash."""
    try:
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
    except Exception:
        return False


async def get_user_by_username(username: str):
    """Get user by username (for password-based login)."""
    if not username or not await ensure_database():
        return None
    async with _db_pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT * FROM gateway_users WHERE username = $1 AND enabled = true",
            username,
        )
        return dict(row) if row else None


async def verify_user_password(username: str, password: str):
    """Verify username and password, return user if valid."""
    user = await get_user_by_username(username)
    if not user:
        return None
    password_hash = user.get("password_hash")
    if not password_hash:
        return None
    if verify_password(password, password_hash):
        return user
    return None


async def change_user_password(user_id: int, old_password: str, new_password: str):
    """Change user password after verifying old password."""
    if not await ensure_database():
        return {"success": False, "error": "数据库未连接"}

    async with _db_pool.acquire() as connection:
        row = await connection.fetchrow(
            "SELECT password_hash FROM gateway_users WHERE id = $1",
            user_id,
        )
        if not row:
            return {"success": False, "error": "用户不存在"}

        current_hash = row["password_hash"]
        if not current_hash or not verify_password(old_password, current_hash):
            return {"success": False, "error": "原密码错误"}

        new_hash = hash_password(new_password)
        await connection.execute(
            "UPDATE gateway_users SET password_hash = $2, updated_at = now() WHERE id = $1",
            user_id,
            new_hash,
        )
        return {"success": True}


async def admin_reset_user_password(user_id: int):
    """Admin resets user password to default 123456."""
    if not await ensure_database():
        return None
    default_hash = hash_password("123456")
    async with _db_pool.acquire() as connection:
        row = await connection.fetchrow(
            "UPDATE gateway_users SET password_hash = $2, updated_at = now() WHERE id = $1 RETURNING *",
            user_id,
            default_hash,
        )
        return dict(row) if row else None


async def reset_user_key(user_id: int, api_key: str):
    if not await ensure_database():
        return None
    async with _db_pool.acquire() as connection:
        row = await connection.fetchrow(
            "UPDATE gateway_users SET api_key = $2, updated_at = now() WHERE id = $1 RETURNING *",
            user_id,
            api_key,
        )
        return dict(row) if row else None


async def write_usage_and_conversation(
    *,
    user_id,
    username: str,
    ip_address: str | None,
    request_id: str,
    model_name: str,
    upstream_model_name: str | None,
    service_name: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    input_price: float,
    output_price: float,
    total_price: float,
    currency: str,
    stream: bool,
    status_code: int | None,
    latency_ms: int | None,
    success: bool,
    user_prompt: str,
    assistant_response: str,
    prompt_truncated: bool,
    response_truncated: bool,
):
    if not await ensure_database():
        return False
    total_tokens = prompt_tokens + completion_tokens
    async with _db_pool.acquire() as connection:
        async with connection.transaction(isolation='serializable'):
            usage_row = await connection.fetchrow(
                """
                INSERT INTO gateway_usage_logs (
                    created_at, user_id, username, ip_address, request_id, model_name, upstream_model_name,
                    service_name, prompt_tokens, completion_tokens, total_tokens,
                    input_price, output_price, total_price, currency, stream, status_code,
                    latency_ms, success
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
                RETURNING id;
                """,
                adjusted_now(), user_id, username, ip_address, request_id, model_name, upstream_model_name,
                service_name, prompt_tokens, completion_tokens, total_tokens,
                input_price, output_price, total_price, currency, stream, status_code,
                latency_ms, success,
            )
            if user_id is not None:
                await connection.execute(
                    "UPDATE gateway_users SET quota_used = quota_used + $2, updated_at = now() WHERE id = $1",
                    user_id,
                    total_price,
                )
            await connection.execute(
                """
                INSERT INTO gateway_conversation_logs (
                    created_at, usage_log_id, user_id, username, request_id, model_name, user_prompt,
                    assistant_response, prompt_truncated, response_truncated
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10);
                """,
                adjusted_now(), usage_row["id"], user_id, username, request_id, model_name, user_prompt,
                assistant_response, prompt_truncated, response_truncated,
            )
    return True


async def get_usage_summary(
    minutes: int | None = None,
    days: int | None = None,
    user_id: int | None = None,
    username: str | None = None,
    model_name: str | None = None,
):
    if not await ensure_database():
        return []
    if days is not None:
        cutoff_time = adjusted_now() - timedelta(days=days)
    else:
        cutoff_time = adjusted_now() - timedelta(minutes=minutes or 60)

    where_parts = ["created_at >= $1"]
    args = [cutoff_time]
    if user_id is not None:
        args.append(user_id)
        where_parts.append(f"user_id = ${len(args)}")
    if username:
        args.append(username)
        where_parts.append(f"username = ${len(args)}")
    if model_name:
        args.append(model_name)
        where_parts.append(f"model_name = ${len(args)}")

    where = " AND ".join(where_parts)

    day_boundary_expr = "((created_at AT TIME ZONE 'Asia/Shanghai') - interval '1 hour')::date"
    now_shanghai = adjusted_now()
    today_boundary = (now_shanghai - timedelta(hours=1)).date()
    args_len = len(args)
    args.append(today_boundary)

    sql = f"""
    SELECT user_id, username, model_name,
           SUM(prompt_tokens)::BIGINT AS prompt_tokens,
           SUM(completion_tokens)::BIGINT AS completion_tokens,
           SUM(total_tokens)::BIGINT AS total_tokens,
           SUM(total_price)::NUMERIC(18,8) AS total_price,
           SUM(CASE WHEN {day_boundary_expr} >= ${args_len + 1} THEN total_price ELSE 0 END)::NUMERIC(18,8) AS daily_price,
           COUNT(*)::BIGINT AS request_count
    FROM gateway_usage_logs
    WHERE {where}
    GROUP BY user_id, username, model_name
    ORDER BY total_tokens DESC;
    """
    async with _db_pool.acquire() as connection:
        rows = await connection.fetch(sql, *args)
        return [dict(row) for row in rows]


async def get_model_daily_requests(user_id: int | None = None):
    if not await ensure_database():
        return []
    now = adjusted_now()
    today = (now - timedelta(hours=1)).date()
    start_date = today - timedelta(days=29)
    end_date = today + timedelta(days=1)
    day_expr = "((created_at AT TIME ZONE 'Asia/Shanghai') - interval '1 hour')::date"
    where_parts = [f"{day_expr} >= $1", f"{day_expr} < $2"]
    args = [start_date, end_date]
    if user_id is not None:
        args.append(user_id)
        where_parts.append(f"user_id = ${len(args)}")
    where = " AND ".join(where_parts)
    sql = f"""
    SELECT {day_expr} AS day,
           model_name,
           COALESCE(SUM(prompt_tokens), 0)::BIGINT AS prompt_tokens
    FROM gateway_usage_logs
    WHERE {where}
    GROUP BY day, model_name
    ORDER BY day ASC, model_name ASC;
    """
    async with _db_pool.acquire() as connection:
        rows = await connection.fetch(sql, *args)
        raw_rows = [dict(row) for row in rows]
    models = sorted({row["model_name"] for row in raw_rows})
    count_map = {(row["day"], row["model_name"]): row["prompt_tokens"] for row in raw_rows}
    result = []
    for offset in range(30):
        day = start_date + timedelta(days=offset)
        for model_name in models:
            result.append({
                "day": day.isoformat(),
                "model_name": model_name,
                "prompt_tokens": int(count_map.get((day, model_name), 0)),
            })
    return result


async def get_conversations(
    minutes: int | None = None,
    days: int | None = None,
    user_id: int | None = None,
    username: str | None = None,
    model_name: str | None = None,
    limit: int = 100,
):
    if not await ensure_database():
        return []
    if days is not None:
        cutoff_time = adjusted_now() - timedelta(days=days)
    else:
        cutoff_time = adjusted_now() - timedelta(minutes=minutes or 60)
    where_parts = ["c.created_at >= $1"]
    args = [cutoff_time]
    if user_id is not None:
        args.append(user_id)
        where_parts.append(f"c.user_id = ${len(args)}")
    if username:
        args.append(username)
        where_parts.append(f"c.username = ${len(args)}")
    if model_name:
        args.append(model_name)
        where_parts.append(f"c.model_name = ${len(args)}")
    args.append(limit)
    limit_index = len(args)
    where = " AND ".join(where_parts)
    sql = f"""
    SELECT c.id, c.created_at, c.user_id, c.username, c.request_id, c.model_name,
           c.user_prompt, c.assistant_response,
           COALESCE(u.prompt_tokens, 0) AS prompt_tokens,
           COALESCE(u.completion_tokens, 0) AS completion_tokens,
           COALESCE(u.total_tokens, 0) AS total_tokens
    FROM gateway_conversation_logs c
    LEFT JOIN gateway_usage_logs u ON u.id = c.usage_log_id
    WHERE {where}
    ORDER BY c.created_at DESC
    LIMIT ${limit_index};
    """
    async with _db_pool.acquire() as connection:
        rows = await connection.fetch(sql, *args)
        return [dict(row) for row in rows]

async def write_model_usage(
    service_name: str,
    model_name: str,
    count: int = 1,
    request=None,
    timestamp: Optional[datetime] = None
) -> bool:
    """
    异步写入模型使用日志到数据库
    
    Args:
        service_name (str): 服务名称
        model_name (str): 模型名称
        count (int): 使用次数，默认为1
        request (Request, optional): FastAPI请求对象，用于提取IP地址和内容长度
        timestamp (datetime, optional): 时间戳，默认为当前时间
        
    Returns:
        bool: 写入是否成功
    """
    global _db_pool
    
    # 如果没有提供时间戳，则使用当前时间
    if timestamp is None:
        timestamp = adjusted_now()
    
    # 初始化ip_address和content_length
    ip_address = None
    content_length = None
    
    # 如果提供了request对象，则从中提取IP地址和content-length
    if request is not None:
        # 提取IP地址：优先使用x-forwarded-for，如果没有则使用host
        ip_address = request.headers.get('x-forwarded-for')
        if not ip_address:
            ip_address = request.headers.get('host')
        
        # 提取content-length
        content_length_str = request.headers.get('content-length')
        content_length = int(content_length_str) if content_length_str and content_length_str.isdigit() else None
    
    # 检查数据库连接
    if not _db_pool:
        if not await _reconnect_database():
            return False
    
    # 如果还是没有连接成功
    if not _db_pool:
        return False
    
    try:
        insert_sql = """
        INSERT INTO api_models_use_log (timestamp, service_name, model_name, count, ip_address, content_length)
        VALUES ($1, $2, $3, $4, $5, $6);
        """
        
        async with _db_pool.acquire() as connection:
            await connection.execute(insert_sql, timestamp, service_name, model_name, count, ip_address, content_length)
        
        return True
        
    except asyncpg.exceptions.ConnectionDoesNotExistError:
        # 连接丢失，尝试重连并重新执行
        if await _reconnect_database():
            try:
                async with _db_pool.acquire() as connection:
                    await connection.execute(insert_sql, timestamp, service_name, model_name, count, ip_address, content_length)
                return True
            except Exception:
                return False
        else:
            return False
    except Exception:
        return False

async def write_scheduler_monitor_data(
    model_name: str,
    gpu_usage: float,
    num_requests_waiting: int,
    pending_requests: int,
    low_priority_pending_requests: int,
    num_requests_running: int,
    queue_length: int,
    timestamp: Optional[datetime] = None
) -> bool:
    """
    异步写入调度器监控数据到数据库
    
    Args:
        model_name (str): 模型名称
        gpu_usage (float): GPU使用率
        num_requests_waiting (int): 等待请求数
        pending_requests (int): 未收到响应的请求数
        low_priority_pending_requests (int): 低优先级未收到响应的请求数
        num_requests_running (int): 正在运行的请求数
        queue_length (int): 队列长度
        timestamp (datetime, optional): 时间戳，默认为当前时间
        
    Returns:
        bool: 写入是否成功
    """
    global _db_pool
    
    # 如果没有提供时间戳，则使用当前时间
    if timestamp is None:
        timestamp = adjusted_now()
    
    # 检查数据库连接
    if not _db_pool:
        if not await _reconnect_database():
            return False
    
    # 如果还是没有连接成功
    if not _db_pool:
        return False
    
    try:
        insert_sql = """
        INSERT INTO llm_gateway_scheduler_monitor_log (
            timestamp, model_name, gpu_usage, num_requests_waiting, 
            pending_requests, low_priority_pending_requests, 
            num_requests_running, queue_length
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
        """
        
        async with _db_pool.acquire() as connection:
            await connection.execute(
                insert_sql, 
                timestamp, model_name, gpu_usage, num_requests_waiting,
                pending_requests, low_priority_pending_requests,
                num_requests_running, queue_length
            )
        
        return True
        
    except asyncpg.exceptions.ConnectionDoesNotExistError:
        # 连接丢失，尝试重连并重新执行
        if await _reconnect_database():
            try:
                async with _db_pool.acquire() as connection:
                    await connection.execute(
                        insert_sql, 
                        timestamp, model_name, gpu_usage, num_requests_waiting,
                        pending_requests, low_priority_pending_requests,
                        num_requests_running, queue_length
                    )
                return True
            except Exception:
                return False
        else:
            return False
    except Exception:
        return False

async def get_all_scheduler_monitor_data_average(
    minutes: int = 1440  # 默认24小时
) -> Dict[str, pd.DataFrame]:
    """
    查询所有模型最近几分钟的调度器监控数据平均值，并对缺失的时间节点添加0值
    
    Args:
        minutes (int): 查询分钟数，默认为1440分钟（24小时）
        
    Returns:
        Dict[str, pd.DataFrame]: 以model_name为键，对应的DataFrame为值的字典
    """
    global _db_pool
    
    if not _db_pool:
        if not await _reconnect_database():
            return {}
    
    if not _db_pool:
        return {}
    
    try:
        # 计算时间截止点
        cutoff_time = adjusted_now() - timedelta(minutes=minutes)
        
        select_sql = """
        SELECT 
            model_name,
            date_trunc('minute', timestamp) AS minute_timestamp,
            AVG(gpu_usage) AS avg_gpu_usage,
            AVG(num_requests_waiting) AS avg_num_requests_waiting,
            AVG(pending_requests) AS avg_pending_requests,
            AVG(low_priority_pending_requests) AS avg_low_priority_pending_requests,
            AVG(num_requests_running) AS avg_num_requests_running,
            AVG(queue_length) AS avg_queue_length
        FROM llm_gateway_scheduler_monitor_log
        WHERE timestamp >= $1
        GROUP BY model_name, minute_timestamp
        ORDER BY model_name, minute_timestamp;
        """
        
        async with _db_pool.acquire() as connection:
            rows = await connection.fetch(select_sql, cutoff_time)
            
            # 转换为字典列表并按模型分组
            model_data = {}

            for row in rows:
                model_name = row['model_name']
                # 将数据库中的UTC时间转换为本地时间（UTC+8）
                utc_timestamp = row['minute_timestamp']
                if utc_timestamp.tzinfo is not None:
                    # 如果有tzinfo，则进行时区转换
                    local_timestamp = utc_timestamp.replace(tzinfo=None) + timedelta(hours=8)
                else:
                    # 如果没有tzinfo，假设它是UTC时间，加上8小时
                    local_timestamp = utc_timestamp + timedelta(hours=8)
                
                # 按模型分组存储数据
                if model_name not in model_data:
                    model_data[model_name] = {}
                    
                model_data[model_name][local_timestamp] = {
                    "model_name": model_name,
                    "timestamp": local_timestamp,
                    "avg_gpu_usage": float(row['avg_gpu_usage']) if row['avg_gpu_usage'] is not None else 0.0,
                    "avg_num_requests_waiting": int(row['avg_num_requests_waiting']) if row['avg_num_requests_waiting'] is not None else 0,
                    "avg_pending_requests": int(row['avg_pending_requests']) if row['avg_pending_requests'] is not None else 0,
                    "avg_low_priority_pending_requests": int(row['avg_low_priority_pending_requests']) if row['avg_low_priority_pending_requests'] is not None else 0,
                    "avg_num_requests_running": int(row['avg_num_requests_running']) if row['avg_num_requests_running'] is not None else 0,
                    "avg_queue_length": int(row['avg_queue_length']) if row['avg_queue_length'] is not None else 0
                }
            
            # 生成完整的时间序列（最近minutes分钟，每分钟一个时间戳）
            now = adjusted_now()
            all_timestamps = []
            for i in range(minutes):
                timestamp = now - timedelta(minutes=i)
                # 将时间戳截断到分钟级别以匹配数据库中的格式
                timestamp = timestamp.replace(second=0, microsecond=0)
                all_timestamps.append(timestamp)
            
            # 创建结果字典
            result = {}

            # 如果没有模型，直接返回空字典
            if not model_data:
                return {}

            # 为每个模型创建DataFrame
            for model_name in model_data.keys():
                # 创建该模型的数据列表
                model_records = []
                
                # 为每个时间戳创建记录
                for timestamp in all_timestamps:
                    if model_name in model_data and timestamp in model_data[model_name]:
                        # 如果存在实际数据，使用实际数据
                        model_records.append(model_data[model_name][timestamp])
                    else:
                        # 如果不存在数据，创建默认值为0的记录
                        model_records.append({
                            "model_name": model_name,
                            "timestamp": timestamp,
                            "avg_gpu_usage": 0.0,
                            "avg_num_requests_waiting": 0,
                            "avg_pending_requests": 0,
                            "avg_low_priority_pending_requests": 0,
                            "avg_num_requests_running": 0,
                            "avg_queue_length": 0
                        })

                # 创建DataFrame并以model_name为键存入结果字典
                df = pd.DataFrame(model_records)
                result[model_name] = df
                
                # # 保存为CSV文件
                # csv_filename = f"{model_name}_scheduler_data.csv"
                # df.to_csv(csv_filename, index=False)
            return result
            
    except Exception as e:
        print(f"查询调度器监控数据时出错: {e}")
        return {}
