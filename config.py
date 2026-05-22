"""
PDF 翻译应用配置
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 路径配置
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
OUTPUT_FOLDER = os.path.join(BASE_DIR, 'output')
TEMP_FOLDER = os.path.join(BASE_DIR, 'temp')
DATA_FOLDER = os.path.join(BASE_DIR, 'data', 'sessions')

# 翻译配置
TRANSLATION_SOURCE = 'en'       # 源语言
TRANSLATION_TARGET = 'zh-CN'    # 目标语言
TRANSLATION_DELAY = 0.1         # 翻译请求间隔（秒）

# 公式检测配置
FORMULA_DETECTION_THRESHOLD = 0.15  # 数学符号密度阈值

# 文件大小限制
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200MB (单个文件)
MAX_FILE_SIZE_REBUILD = 500 * 1024 * 1024  # 500MB (对译重建，两个文件)
MAX_PAGES = 500                    # 最大页数

# Celery 配置
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'

# Redis 配置
REDIS_HOST = 'localhost'
REDIS_PORT = 6379

# 翻译服务配置
TRANSLATION_SERVICE = "ollama"          # "ollama" 或 "openai"
OLLAMA_MODEL = "translategemma:27b"
OLLAMA_URL = "http://localhost:11434"

# OpenAI 兼容配置（默认 DeepSeek）
OPENAI_MODEL = "deepseek-v4-flash"
OPENAI_BASE_URL = "https://api.deepseek.com"
OPENAI_API_KEY = ""

# 用户设置持久化
SETTINGS_FILE = os.path.join(BASE_DIR, 'data', 'settings.json')

# 小字跳过阈值（字号小于此值的文本块不翻译）
MIN_FONT_SIZE_TO_TRANSLATE = 7.0

# 翻译缓存
TRANSLATION_CACHE_DIR = os.path.join(BASE_DIR, 'data', 'cache')


def allowed_file(filename):
    """检查文件扩展名"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'pdf'


def ensure_dirs():
    """确保所有必要目录存在"""
    for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, TEMP_FOLDER, DATA_FOLDER, TRANSLATION_CACHE_DIR]:
        os.makedirs(folder, exist_ok=True)


import json

DEFAULT_SETTINGS = {
    "engine": "ollama",
    "ollama_model": OLLAMA_MODEL,
    "ollama_url": OLLAMA_URL,
    "openai_model": OPENAI_MODEL,
    "openai_base_url": OPENAI_BASE_URL,
    "openai_api_key": "",
}

def load_settings():
    """从文件加载用户设置"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            # 合并默认值（防止缺少新字段）
            result = dict(DEFAULT_SETTINGS)
            result.update(saved)
            return result
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)

def save_settings(settings: dict):
    """保存用户设置到文件"""
    os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
    # 只保存已知字段
    data = {}
    for key in DEFAULT_SETTINGS:
        if key in settings:
            data[key] = settings[key]
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
