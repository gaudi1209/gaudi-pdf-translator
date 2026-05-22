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


def allowed_file(filename):
    """检查文件扩展名"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() == 'pdf'


def ensure_dirs():
    """确保所有必要目录存在"""
    for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, TEMP_FOLDER, DATA_FOLDER]:
        os.makedirs(folder, exist_ok=True)
