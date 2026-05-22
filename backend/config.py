import os

# Redis配置
REDIS_CONFIG = {
    "host": os.getenv("REDIS_HOST", "localhost"),
    "port": int(os.getenv("REDIS_PORT", 16379)),
    "decode_responses": False,  # 禁用自动解码，返回原始bytes
    "password": os.getenv("REDIS_PASSWORD", None)
}

# 性能统计配置
PERFORMANCE_STATS = {
    "enabled": False  # 是否启用性能统计功能
}

# PostgreSQL配置
DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", 5432)),
    "database": os.getenv("POSTGRES_DB", "llm_data"),
    "user": os.getenv("POSTGRES_USER", "llm_user"),
    "password": os.getenv("POSTGRES_PASSWORD", "llm_password"),
}

# 动态配置文件。日志配置仍保留在本 Python 文件中。
RUNTIME_CONFIG_PATH = os.getenv(
    "RUNTIME_CONFIG_PATH",
    os.path.join(os.path.dirname(__file__), "runtime_config.json")
)

# tiktoken 本地缓存目录
TIKTOKEN_CACHE_DIR = os.getenv(
    "TIKTOKEN_CACHE_DIR",
    os.path.join(os.path.dirname(__file__), "tiktoken-cache")
)

# 初始超级用户，未设置时不会自动创建
INITIAL_ADMIN_USERNAME = os.getenv("INITIAL_ADMIN_USERNAME", "admin")
INITIAL_ADMIN_API_KEY = os.getenv("INITIAL_ADMIN_API_KEY", "admin@test.com")
INITIAL_ADMIN_PASSWORD = os.getenv("INITIAL_ADMIN_PASSWORD", "admin@test.com")

# 日志配置
from loguru import logger
import os

# 创建日志目录（如果不存在）
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)

# 添加文件处理器 - 保留10天日志
# 共享日志配置（用于两个进程共享同一个日志文件）
shared_log_file = os.path.join(log_dir, "app.log")

# 移除默认的stderr处理器（可选）
logger.remove()

logger.add(
    shared_log_file,
    rotation="50 MB",      # 文件达到500MB时轮转
    retention="10 days",    # 保留10天的日志
    level="DEBUG",          # 记录DEBUG级别及以上的日志
    #format="{time:YYYY-MM-DD HH:mm:ss} |{function}:{line} - {message}"
    format="{time:YYYY-MM-DD HH:mm:ss}|{message}"
)

# 现在所有的日志都会记录到这个文件
logger.info("日志配置初始化完成")
logger.info("这会记录到 app.log")
logger.error("错误信息也会记录到这里")
