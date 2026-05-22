"""
PDF 翻译主处理流水线
支持分批处理和断点续传
"""
import os
import fitz
import time
import re
from typing import Callable, Optional, List
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

from core.pdf_parser import PDFParser, PageInfo, TextBlock, ChapterInfo
from services.google_translate import ProtectedTranslator
from core.pdf_rebuilder import PDFRebuilder
from core.progress_manager import ProgressManager


class ProcessingStatus(Enum):
    PENDING = "pending"
    PARSING = "parsing"
    TRANSLATING = "translating"
    REBUILDING = "rebuilding"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TranslationStats:
    """翻译统计信息"""
    duration_seconds: float = 0.0
    total_chars: int = 0  # 不含标点的字符数
    total_words: int = 0  # 英文单词数
    translated_blocks: int = 0
    skipped_blocks: int = 0

    def to_dict(self):
        return {
            'duration_seconds': round(self.duration_seconds, 1),
            'duration_formatted': self._format_duration(self.duration_seconds),
            'total_chars': self.total_chars,
            'total_words': self.total_words,
            'translated_blocks': self.translated_blocks,
            'skipped_blocks': self.skipped_blocks
        }

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """格式化时长"""
        if seconds < 60:
            return f"{seconds:.1f}秒"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}分{secs}秒"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}小时{minutes}分"


@dataclass
class ProcessingProgress:
    """处理进度"""
    status: ProcessingStatus
    current_page: int
    total_pages: int
    current_block: int
    total_blocks: int
    message: str
    error: Optional[str] = None
    stats: TranslationStats = field(default_factory=TranslationStats)

    def to_dict(self):
        return {
            'status': self.status.value,
            'current_page': self.current_page,
            'total_pages': self.total_pages,
            'current_block': self.current_block,
            'total_blocks': self.total_blocks,
            'message': self.message,
            'error': self.error,
            'stats': self.stats.to_dict()
        }


class PDFTranslationProcessor:
    """PDF 翻译处理器 - 支持按章节分批处理和断点续传"""

    def __init__(self,
                 input_path: str,
                 output_path: str,
                 max_workers: int = 10,
                 data_dir: str = None):
        self.input_path = input_path
        self.output_path = output_path
        self.max_workers = max_workers
        self.data_dir = data_dir or os.path.join(os.path.dirname(input_path), 'data', 'sessions')

        self.parser = None
        self.pages_info: List[PageInfo] = []
        self.chapters: List[ChapterInfo] = []
        self.translator = ProtectedTranslator()

        self.progress_callback: Optional[Callable] = None
        self.status = ProcessingStatus.PENDING
        self.progress_manager: Optional[ProgressManager] = None

        self._processed_blocks = 0
        self._lock = threading.Lock()

        # 翻译统计
        self._stats = TranslationStats()
        self._start_time = 0.0

    def set_progress_callback(self, callback: Callable):
        self.progress_callback = callback

    def _update_progress(self, progress: ProcessingProgress):
        self.status = progress.status
        if self.progress_callback:
            self.progress_callback(progress)

    @staticmethod
    def _count_chars_without_punctuation(text: str) -> int:
        """统计不含标点符号的字符数"""
        if not text:
            return 0
        # 移除中文标点
        text = re.sub(r'[，。！？、；：""''【】《》（）\s]', '', text)
        # 移除英文标点
        text = re.sub(r'[,.!?;:\'"\[\](){}<>]', '', text)
        return len(text)

    @staticmethod
    def _count_words(text: str) -> int:
        """统计英文单词数（连续的字母序列）"""
        if not text:
            return 0
        # 匹配英文单词
        words = re.findall(r'[a-zA-Z]+', text)
        return len(words)

    def _translate_block(self, block: TextBlock) -> TextBlock:
        """翻译单个文本块"""
        if block.should_translate and block.text:
            result = self.translator.translate_with_protection(block.text)
            if result.success:
                block.translated_text = result.translated
            else:
                block.translated_text = block.text
        return block

    def process(self, task_id: str = None, resume: bool = True) -> str:
        """执行完整处理流程 - 按章节分批

        Args:
            task_id: 任务ID，用于断点续传
            resume: 是否尝试从断点恢复
        """
        try:
            # 开始计时
            self._start_time = time.time()
            self._stats = TranslationStats()

            # 初始化进度管理器
            if task_id:
                self.progress_manager = ProgressManager(task_id, self.data_dir)

                # 尝试恢复进度
                if resume and self.progress_manager.load():
                    print(f"从断点恢复: {self.progress_manager.get_overall_progress()}")

            # 阶段1：解析 PDF
            self._update_progress(ProcessingProgress(
                status=ProcessingStatus.PARSING,
                current_page=0, total_pages=0,
                current_block=0, total_blocks=0,
                message="正在解析 PDF..."
            ))

            self.parser = PDFParser(self.input_path)
            self.pages_info = self.parser.parse()
            self.chapters = self.parser.chapters
            total_pages = len(self.pages_info)

            # 初始化进度管理器
            if self.progress_manager:
                self.progress_manager.total_pages = total_pages
                self.progress_manager.set_status("translating")
                self.progress_manager.save()

            # 统计总块数和跳过的块数
            total_blocks = 0
            skipped_blocks = 0
            for page_info in self.pages_info:
                for block in page_info.blocks:
                    if block.should_translate:
                        total_blocks += 1
                    else:
                        skipped_blocks += 1

            self._stats.skipped_blocks = skipped_blocks
            print(f"PDF解析完成: {total_pages} 页, {len(self.chapters)} 章节, 需翻译 {total_blocks} 块, 跳过 {skipped_blocks} 块")

            # 阶段2：按章节翻译
            self._processed_blocks = 0

            for chapter_idx, chapter in enumerate(self.chapters):
                chapter_msg = f"章节 {chapter_idx + 1}/{len(self.chapters)}: {chapter.title}"
                print(f"\n处理 {chapter_msg}")

                # 检查哪些页面需要翻译（跳过已完成的）
                pages_to_process = []
                for page_num in range(chapter.start_page, chapter.end_page + 1):
                    if self.progress_manager and self.progress_manager.is_page_completed(page_num):
                        print(f"  跳过已完成页面 {page_num + 1}")
                        # 恢复翻译结果
                        translations = self.progress_manager.get_page_translations(page_num)
                        page_info = self.pages_info[page_num]
                        block_idx = 0
                        for block in page_info.blocks:
                            if block.should_translate:
                                if block_idx in translations:
                                    block.translated_text = translations[block_idx]
                                block_idx += 1
                        self._processed_blocks += block_idx
                    else:
                        pages_to_process.append(page_num)

                if not pages_to_process:
                    continue

                # 翻译这章的页面
                self._update_progress(ProcessingProgress(
                    status=ProcessingStatus.TRANSLATING,
                    current_page=chapter.start_page + 1,
                    total_pages=total_pages,
                    current_block=self._processed_blocks,
                    total_blocks=total_blocks,
                    message=f"正在翻译 {chapter_msg}..."
                ))

                # 初始化页面进度
                for page_num in pages_to_process:
                    page_blocks = sum(1 for b in self.pages_info[page_num].blocks if b.should_translate)
                    if self.progress_manager:
                        self.progress_manager.init_page(page_num, page_blocks)

                # 收集这章需要翻译的块
                chapter_blocks = []
                for page_num in pages_to_process:
                    page_info = self.pages_info[page_num]
                    for block_idx, block in enumerate(page_info.blocks):
                        if block.should_translate:
                            chapter_blocks.append((page_num, block_idx, block))

                # 多线程翻译
                with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = {
                        executor.submit(self._translate_block, block): (page_num, block_idx)
                        for page_num, block_idx, block in chapter_blocks
                    }

                    for future in as_completed(futures):
                        page_num, block_idx = futures[future]
                        try:
                            translated_block = future.result()

                            # 统计字数（使用翻译后的文本）
                            with self._lock:
                                self._stats.translated_blocks += 1
                                self._stats.total_chars += self._count_chars_without_punctuation(translated_block.translated_text)
                                self._stats.total_words += self._count_words(translated_block.translated_text)

                            # 保存翻译结果
                            if self.progress_manager:
                                self.progress_manager.update_block(
                                    page_num, block_idx, translated_block.translated_text
                                )

                            with self._lock:
                                self._processed_blocks += 1
                                current = self._processed_blocks

                            # 更新进度
                            if current % 5 == 0 or current == total_blocks:
                                # 计算当前时长
                                elapsed = time.time() - self._start_time
                                current_stats = TranslationStats(
                                    duration_seconds=elapsed,
                                    total_chars=self._stats.total_chars,
                                    total_words=self._stats.total_words,
                                    translated_blocks=self._stats.translated_blocks,
                                    skipped_blocks=self._stats.skipped_blocks
                                )
                                self._update_progress(ProcessingProgress(
                                    status=ProcessingStatus.TRANSLATING,
                                    current_page=chapter.end_page + 1,
                                    total_pages=total_pages,
                                    current_block=current,
                                    total_blocks=total_blocks,
                                    message=f"正在翻译 {chapter_msg} ({current}/{total_blocks})",
                                    stats=current_stats
                                ))

                                # 定期保存进度
                                if self.progress_manager:
                                    self.progress_manager.save()

                        except Exception as e:
                            print(f"翻译块失败 (page {page_num}, block {block_idx}): {e}")

                # 标记这章页面完成
                for page_num in pages_to_process:
                    if self.progress_manager:
                        self.progress_manager.complete_page(page_num)

                # 保存进度
                if self.progress_manager:
                    self.progress_manager.save()

            # 阶段3：重建 PDF
            self._update_progress(ProcessingProgress(
                status=ProcessingStatus.REBUILDING,
                current_page=total_pages, total_pages=total_pages,
                current_block=total_blocks, total_blocks=total_blocks,
                message="正在重建 PDF...",
                stats=self._stats
            ))

            rebuilder = PDFRebuilder(self.output_path)
            output_path = rebuilder.rebuild_from_original(self.input_path, self.pages_info)

            # 计算总时长
            self._stats.duration_seconds = time.time() - self._start_time

            # 打印统计信息
            print(f"\n翻译统计:")
            print(f"  时长: {self._stats._format_duration(self._stats.duration_seconds)}")
            print(f"  字符数（不含标点）: {self._stats.total_chars}")
            print(f"  英文单词数: {self._stats.total_words}")
            print(f"  翻译块数: {self._stats.translated_blocks}")
            print(f"  跳过块数: {self._stats.skipped_blocks}")

            # 清理进度文件
            if self.progress_manager:
                self.progress_manager.set_status("completed")
                self.progress_manager.save()

            self._update_progress(ProcessingProgress(
                status=ProcessingStatus.COMPLETED,
                current_page=total_pages, total_pages=total_pages,
                current_block=total_blocks, total_blocks=total_blocks,
                message=f"翻译完成！时长: {self._stats._format_duration(self._stats.duration_seconds)}, 字数: {self._stats.total_chars}",
                stats=self._stats
            ))

            return output_path

        except Exception as e:
            error_msg = str(e)
            print(f"处理失败: {error_msg}")

            if self.progress_manager:
                self.progress_manager.set_status("failed")
                self.progress_manager.save()

            self._update_progress(ProcessingProgress(
                status=ProcessingStatus.FAILED,
                current_page=0, total_pages=0,
                current_block=0, total_blocks=0,
                message="处理失败",
                error=error_msg
            ))
            raise

        finally:
            if self.parser:
                self.parser.close()


def translate_pdf(input_path: str, output_path: str,
                  progress_callback: Optional[Callable] = None,
                  max_workers: int = 10,
                  task_id: str = None,
                  resume: bool = True) -> str:
    """便捷函数：翻译 PDF

    Args:
        input_path: 输入PDF路径
        output_path: 输出PDF路径
        progress_callback: 进度回调函数
        max_workers: 并行线程数
        task_id: 任务ID（用于断点续传）
        resume: 是否从断点恢复
    """
    processor = PDFTranslationProcessor(input_path, output_path, max_workers)
    if progress_callback:
        processor.set_progress_callback(progress_callback)
    return processor.process(task_id=task_id, resume=resume)
