"""
PDF 翻译 Web 应用 - Flask 主入口
"""
import os
import sys

# 设置控制台编码为 UTF-8（Windows 兼容）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import uuid
import threading
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
import fitz

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import *
from config import load_settings, save_settings
from core.processor import PDFTranslationProcessor, ProcessingStatus
from core.ebook_processor import EbookTranslator, EbookStatus

# 确保目录存在
ensure_dirs()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'pdf-translator-secret-key'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE_REBUILD  # 使用更大的限制以支持对译重建

# 存储任务状态
tasks = {}
tasks_lock = threading.Lock()


@app.route('/')
def index():
    """首页"""
    return render_template('index.html')


@app.route('/api/translation-config')
def get_translation_config():
    """获取翻译服务配置（从持久化设置中读取）"""
    settings = load_settings()
    return jsonify({
        'engine': settings.get('engine', 'ollama'),
        'ollama_model': settings.get('ollama_model', OLLAMA_MODEL),
        'ollama_url': settings.get('ollama_url', OLLAMA_URL),
        'openai_model': settings.get('openai_model', OPENAI_MODEL),
        'openai_base_url': settings.get('openai_base_url', OPENAI_BASE_URL),
        'openai_api_key': settings.get('openai_api_key', ''),
    })


@app.route('/api/save-settings', methods=['POST'])
def api_save_settings():
    """保存翻译引擎设置"""
    data = request.get_json() or {}
    save_settings(data)
    return jsonify({'success': True})


@app.route('/api/upload', methods=['POST'])
def upload():
    """上传文件（PDF / EPUB）"""
    if 'file' not in request.files:
        return jsonify({'error': '没有上传文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ('pdf', 'epub'):
        return jsonify({'error': '只支持 PDF 和 EPUB 文件'}), 400

    # 生成任务ID
    task_id = str(uuid.uuid4())

    # 保存文件
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    saved_name = f"{task_id}_{timestamp}.{ext}"
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], saved_name)
    file.save(filepath)

    # 获取文件信息
    file_type = ext
    page_count = 0
    if ext == 'pdf':
        doc = fitz.open(filepath)
        page_count = len(doc)
        doc.close()
    elif ext == 'epub':
        from ebooklib import epub as epublib
        book = epublib.read_epub(filepath)
        page_count = sum(1 for item in book.get_items() if item.get_type() == 9)

    # 存储任务信息
    with tasks_lock:
        tasks[task_id] = {
            'filename': filename,
            'filepath': filepath,
            'file_type': file_type,
            'page_count': page_count,
            'status': 'uploaded',
            'created_at': datetime.now().isoformat(),
            'progress': None
        }

    return jsonify({
        'success': True,
        'task_id': task_id,
        'filename': filename,
        'file_type': file_type,
        'page_count': page_count
    })


@app.route('/api/translate/<task_id>', methods=['POST'])
def start_translation(task_id):
    """开始翻译任务"""
    with tasks_lock:
        if task_id not in tasks:
            return jsonify({'error': '任务不存在'}), 404

        task = tasks[task_id]

    # 获取翻译参数
    data = request.get_json() or {}
    max_workers = data.get('max_workers', 10)  # 并行线程数

    # 输出文件路径
    file_type = task.get('file_type', 'pdf')
    base_name = task['filename'].rsplit('.', 1)[0]
    if file_type == 'epub':
        output_name = f"bilingual_{base_name}.epub"
    else:
        output_name = f"translated_{task['filename']}"
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_name)

    # 更新状态
    with tasks_lock:
        tasks[task_id]['status'] = 'processing'
        tasks[task_id]['max_workers'] = max_workers

    # 在后台线程中启动翻译
    def run_translation():
        try:
            def progress_callback(progress):
                with tasks_lock:
                    if task_id in tasks:
                        tasks[task_id]['progress'] = progress.to_dict()
                        tasks[task_id]['status'] = progress.status.value

            # 构建翻译配置（从前端传入 + 持久化设置合并）
            settings = load_settings()
            translation_service = data.get('translation_service', settings.get('engine', 'ollama'))

            translation_config = None
            if translation_service == 'openai':
                translation_config = {
                    'service': 'openai',
                    'model': data.get('openai_model') or settings.get('openai_model', OPENAI_MODEL),
                    'base_url': data.get('openai_base_url') or settings.get('openai_base_url', OPENAI_BASE_URL),
                    'api_key': data.get('openai_api_key') or settings.get('openai_api_key', ''),
                }
            elif translation_service == 'ollama':
                translation_config = {
                    'service': 'ollama',
                    'model': data.get('ollama_model') or settings.get('ollama_model', OLLAMA_MODEL),
                    'base_url': data.get('ollama_url') or settings.get('ollama_url', OLLAMA_URL),
                }

            ignore_cache = data.get('ignore_cache', False)

            if file_type == 'epub':
                # EPUB 翻译
                from services.google_translate import get_translator
                cache_dir = os.path.join(os.path.dirname(DATA_FOLDER), 'cache') if DATA_FOLDER else None
                if ignore_cache:
                    cache_dir = None
                config = dict(translation_config or {})
                config['cache_dir'] = cache_dir
                translator = get_translator(**config)

                ebook_translator = EbookTranslator(translator, max_workers=max_workers)
                ebook_translator.set_progress_callback(progress_callback)
                ebook_translator.translate_epub(task['filepath'], output_path)
            else:
                # PDF 翻译
                processor = PDFTranslationProcessor(
                    task['filepath'],
                    output_path,
                    max_workers=max_workers,
                    data_dir=DATA_FOLDER,
                    translation_config=translation_config,
                    ignore_cache=ignore_cache
                )
                processor.set_progress_callback(progress_callback)
                processor.process(task_id=task_id)

            with tasks_lock:
                if task_id in tasks:
                    tasks[task_id]['status'] = 'completed'
                    tasks[task_id]['output_path'] = output_path

        except Exception as e:
            with tasks_lock:
                if task_id in tasks:
                    tasks[task_id]['status'] = 'failed'
                    tasks[task_id]['error'] = str(e)

    thread = threading.Thread(target=run_translation)
    thread.daemon = True
    thread.start()

    return jsonify({
        'success': True,
        'task_id': task_id,
        'status': 'processing'
    })


@app.route('/api/status/<task_id>')
def get_status(task_id):
    """获取任务状态"""
    with tasks_lock:
        if task_id not in tasks:
            return jsonify({'error': '任务不存在'}), 404

        task = tasks[task_id]

    return jsonify({
        'task_id': task_id,
        'status': task.get('status'),
        'progress': task.get('progress'),
        'error': task.get('error')
    })


@app.route('/api/download/<task_id>')
def download(task_id):
    """下载翻译结果"""
    with tasks_lock:
        if task_id not in tasks:
            return jsonify({'error': '任务不存在'}), 404

        task = tasks[task_id]

    if task.get('status') != 'completed':
        return jsonify({'error': '任务未完成'}), 400

    output_path = task.get('output_path')
    if not output_path or not os.path.exists(output_path):
        return jsonify({'error': '文件不存在'}), 404

    base_name = task['filename'].rsplit('.', 1)[0]
    return send_file(
        output_path,
        as_attachment=True,
        download_name=f"bilingual_{base_name}.{task.get('file_type', 'pdf')}"
    )


@app.route('/api/create-interleaved/<task_id>', methods=['POST'])
def create_interleaved(task_id):
    """创建交错双语 PDF（原文+译文交错排列）"""
    from core.pdf_rebuilder import BilingualPDFRebuilder

    with tasks_lock:
        if task_id not in tasks:
            return jsonify({'error': '任务不存在'}), 404
        task = tasks[task_id]

    if task.get('status') != 'completed':
        return jsonify({'error': '任务未完成，无法创建双语对照'}), 400

    original_path = task.get('filepath')
    translated_path = task.get('output_path')

    if not original_path or not os.path.exists(original_path):
        return jsonify({'error': '原始文件不存在'}), 404
    if not translated_path or not os.path.exists(translated_path):
        return jsonify({'error': '翻译文件不存在'}), 404

    # 生成交错双语文件路径
    output_name = f"bilingual_interleaved_{task['filename']}"
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_name)

    try:
        rebuilder = BilingualPDFRebuilder(output_path)
        rebuilder.create_interleaved(original_path, translated_path)

        # 更新任务信息
        with tasks_lock:
            if task_id in tasks:
                tasks[task_id]['interleaved_path'] = output_path

        return jsonify({
            'success': True,
            'message': '交错双语 PDF 创建成功',
            'download_url': f'/api/download-interleaved/{task_id}'
        })
    except Exception as e:
        return jsonify({'error': f'创建失败: {str(e)}'}), 500


@app.route('/api/download-interleaved/<task_id>')
def download_interleaved(task_id):
    """下载交错双语 PDF"""
    with tasks_lock:
        if task_id not in tasks:
            return jsonify({'error': '任务不存在'}), 404
        task = tasks[task_id]

    output_path = task.get('interleaved_path')
    if not output_path or not os.path.exists(output_path):
        return jsonify({'error': '交错双语文件不存在，请先创建'}), 404

    return send_file(
        output_path,
        as_attachment=True,
        download_name=f"bilingual_interleaved_{task['filename']}"
    )


@app.route('/api/rebuild-bilingual', methods=['POST'])
def rebuild_bilingual():
    """对译重建：上传原文和译文PDF，生成交错双语PDF"""
    from core.pdf_rebuilder import BilingualPDFRebuilder

    # 检查文件
    if 'original' not in request.files or 'translated' not in request.files:
        return jsonify({'error': '请上传原文和译文PDF文件'}), 400

    original_file = request.files['original']
    translated_file = request.files['translated']

    if original_file.filename == '' or translated_file.filename == '':
        return jsonify({'error': '请选择原文和译文PDF文件'}), 400

    if not original_file.filename.lower().endswith('.pdf') or not translated_file.filename.lower().endswith('.pdf'):
        return jsonify({'error': '只支持PDF文件'}), 400

    # 生成任务ID
    task_id = str(uuid.uuid4())

    # 保存上传的文件
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    original_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{task_id}_original_{timestamp}.pdf")
    translated_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{task_id}_translated_{timestamp}.pdf")

    original_file.save(original_path)
    translated_file.save(translated_path)

    # 生成输出文件路径
    output_name = f"bilingual_rebuilt_{timestamp}.pdf"
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_name)

    try:
        rebuilder = BilingualPDFRebuilder(output_path)
        rebuilder.create_interleaved(original_path, translated_path)

        # 清理上传的临时文件
        try:
            os.remove(original_path)
            os.remove(translated_path)
        except:
            pass

        return jsonify({
            'success': True,
            'message': '对译重建成功',
            'download_url': f'/api/download-rebuilt/{output_name}'
        })

    except Exception as e:
        # 清理临时文件
        try:
            os.remove(original_path)
            os.remove(translated_path)
        except:
            pass
        return jsonify({'error': f'重建失败: {str(e)}'}), 500


@app.route('/api/download-rebuilt/<filename>')
def download_rebuilt(filename):
    """下载重建的对译PDF"""
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
    if not os.path.exists(output_path):
        return jsonify({'error': '文件不存在'}), 404

    return send_file(
        output_path,
        as_attachment=True,
        download_name=filename
    )


if __name__ == '__main__':
    print("=" * 50)
    print("PDF 翻译 Web 应用")
    print("访问 http://localhost:6500")
    print("=" * 50)
    app.run(debug=True, host='0.0.0.0', port=6500, threaded=True)
