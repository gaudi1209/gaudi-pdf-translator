"""
EPUB 翻译处理器
解析 EPUB 电子书，翻译段落文本，生成双语对照 EPUB
输出结构：一段原文，一段译文
"""
import os
import re
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Callable, Optional
from enum import Enum

from ebooklib import epub
from bs4 import BeautifulSoup, NavigableString, Tag

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.google_translate import ProtectedTranslator


class EbookStatus(Enum):
    PENDING = "pending"
    PARSING = "parsing"
    TRANSLATING = "translating"
    REBUILDING = "rebuilding"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class EbookProgress:
    status: EbookStatus = EbookStatus.PENDING
    current_chapter: int = 0
    total_chapters: int = 0
    current_para: int = 0
    total_paras: int = 0
    message: str = ""

    def to_dict(self):
        return {
            'status': self.status.value,
            'current_chapter': self.current_chapter,
            'total_chapters': self.total_chapters,
            'current_para': self.current_para,
            'total_paras': self.total_paras,
            'message': self.message,
            # 兼容前端 PDF 进度条字段名
            'current_page': self.current_chapter,
            'total_pages': self.total_chapters,
            'current_block': self.current_para,
            'total_blocks': self.total_paras,
        }


# 注入双语样式的 CSS
BILINGUAL_CSS = """
p.original { color: #333; margin-bottom: 0.2em; }
p.translation { color: #1a5276; margin-top: 0.2em; margin-bottom: 1em; font-style: italic; }
"""


class EbookTranslator:
    """EPUB 翻译器 — 一段原文接一段译文"""

    def __init__(self, translator: ProtectedTranslator, max_workers: int = 10):
        self.translator = translator
        self.max_workers = max_workers
        self.progress_callback: Optional[Callable] = None
        self._lock = threading.Lock()
        self._translate_lock = threading.Lock()  # 翻译 API 串行锁
        self._translated_count = 0

    def set_progress_callback(self, callback: Callable):
        self.progress_callback = callback

    def _update_progress(self, progress: EbookProgress):
        if self.progress_callback:
            self.progress_callback(progress)

    def translate_epub(self, input_path: str, output_path: str) -> str:
        """翻译 EPUB，生成双语对照版"""
        progress = EbookProgress()

        # 1. 读取原书
        progress.status = EbookStatus.PARSING
        progress.message = "正在解析 EPUB..."
        self._update_progress(progress)

        book = epub.read_epub(input_path)

        # 收集章节项（类型为 ITEM_DOCUMENT）
        chapters = []
        for item in book.get_items():
            if item.get_type() == 9:  # ebooklib.ITEM_DOCUMENT
                chapters.append(item)

        progress.total_chapters = len(chapters)
        self._update_progress(progress)

        # 2. 提取所有段落并翻译
        #    先解析所有章节，保存 soup 和 content_tags，确保提取和重建使用相同的标签
        progress.status = EbookStatus.TRANSLATING
        all_tasks = []  # [(chapter_idx, para_idx, original_text)]
        chapter_data = []  # [(soup, content_tags)]

        for ch_idx, chapter in enumerate(chapters):
            soup = self._parse_chapter(chapter)
            content_tags = self._get_content_tags(soup)
            chapter_data.append((soup, content_tags))
            for p_idx, tag in enumerate(content_tags):
                text = tag.get_text(strip=True)
                if self._should_translate(text):
                    all_tasks.append((ch_idx, p_idx, text))

        progress.total_paras = len(all_tasks)
        progress.message = f"共 {len(all_tasks)} 段需翻译"
        self._update_progress(progress)

        # 翻译结果存储: {(ch_idx, p_idx): translated_text}
        translations = {}
        self._translated_count = 0

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            for ch_idx, p_idx, text in all_tasks:
                future = executor.submit(self._translate_text, text)
                futures[future] = (ch_idx, p_idx)

            for future in as_completed(futures):
                ch_idx, p_idx = futures[future]
                try:
                    result = future.result()
                    if result:
                        translations[(ch_idx, p_idx)] = result
                except Exception as e:
                    print(f"翻译失败 (ch{ch_idx} p{p_idx}): {e}")

                with self._lock:
                    self._translated_count += 1
                    count = self._translated_count

                if count % 10 == 0 or count == len(all_tasks):
                    progress.current_para = count
                    progress.message = f"翻译中 {count}/{len(all_tasks)}"
                    self._update_progress(progress)

        # 3. 重建双语 EPUB
        progress.status = EbookStatus.REBUILDING
        progress.message = "正在生成双语 EPUB..."
        self._update_progress(progress)

        self._build_bilingual_epub(book, chapters, chapter_data, translations, output_path)

        progress.status = EbookStatus.COMPLETED
        progress.message = f"翻译完成，共翻译 {len(translations)} 段"
        self._update_progress(progress)

        return output_path

    def _parse_chapter(self, chapter) -> BeautifulSoup:
        """解析章节内容"""
        content = chapter.get_content()
        if isinstance(content, bytes):
            content = content.decode('utf-8', errors='replace')
        return BeautifulSoup(content, 'lxml')

    def _get_content_tags(self, soup) -> List:
        """获取包含文本内容的标签列表

        只收集 body 直接子元素中包含文本的标签，避免：
        1. 把嵌套在 <div> 内的 <span> 当作独立段落
        2. 父子标签重复提取
        """
        # 优先找 body 直接子 <p> 标签
        body = soup.find('body')
        if not body:
            return soup.find_all('p') or []

        body_p = [tag for tag in body.find_all('p', recursive=False) if tag.get_text(strip=True)]
        if body_p:
            return body_p

        # 只收集 body 直接子元素中的结构性标签
        tags = []
        for child in body.children:
            if not hasattr(child, 'name') or not child.name:
                continue
            if child.name in ('div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol'):
                text = child.get_text(strip=True)
                if text:
                    tags.append(child)
        return tags

    def _should_translate(self, text: str) -> bool:
        """判断段落是否需要翻译"""
        if not text or len(text.strip()) < 5:
            return False
        # 纯数字/符号跳过
        if re.match(r'^[\d\s\.,;:!?\-–—]+$', text):
            return False
        # 已经是中文为主则跳过
        cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        if cjk / max(len(text), 1) > 0.3:
            return False
        return True

    def _translate_text(self, text: str) -> Optional[str]:
        """翻译单段文本（串行化 API 调用防止并发错位）"""
        with self._translate_lock:
            result = self.translator.translate_with_protection(text)
        if result.success:
            return result.translated
        return None

    def _build_bilingual_epub(self, original_book, chapters, chapter_data, translations, output_path):
        """构建双语 EPUB：一段原文接一段译文"""
        bilingual_book = epub.EpubBook()

        # 复制元数据
        bilingual_book.set_identifier('bilingual_' + str(id(original_book)))
        # 从元数据中提取标题
        title = 'Unknown'
        metadata = original_book.metadata or {}
        for ns, items in metadata.items():
            for key, vals in items.items():
                if 'title' in key.lower():
                    for val, attrs in vals:
                        title = val
                        break
        bilingual_book.set_title(title + ' (双语版)')

        # 提取语言
        lang = 'en'
        for ns, items in metadata.items():
            for key, vals in items.items():
                if 'language' in key.lower():
                    for val, attrs in vals:
                        lang = val
                        break
        bilingual_book.set_language(lang)

        # 提取作者
        for ns, items in metadata.items():
            for key, vals in items.items():
                if 'creator' in key.lower():
                    for val, attrs in vals:
                        bilingual_book.add_author(val)

        # 复制非章节资源（图片、CSS等）
        spine_items = []
        toc_items = []

        for item in original_book.get_items():
            if item.get_type() != 9:  # 非 ITEM_DOCUMENT
                # 复制图片、字体等
                new_item = epub.EpubItem(
                    uid=item.get_id(),
                    file_name=item.get_name(),
                    media_type=item.media_type if hasattr(item, 'media_type') else '',
                    content=item.get_content()
                )
                bilingual_book.add_item(new_item)

        # 添加双语样式
        css_item = epub.EpubItem(
            uid="bilingual_style",
            file_name="bilingual.css",
            media_type="text/css",
            content=BILINGUAL_CSS.encode('utf-8')
        )
        bilingual_book.add_item(css_item)

        # 处理每个章节
        for ch_idx, chapter in enumerate(chapters):
            soup, content_tags = chapter_data[ch_idx]

            # 为每个标签注入译文
            for para_idx, tag in enumerate(content_tags):
                text = tag.get_text(strip=True)
                if not text:
                    continue

                key = (ch_idx, para_idx)
                if key in translations:
                    translated = translations[key]
                    # 在原文标签后插入译文段落
                    trans_tag = soup.new_tag('p', attrs={'class': 'translation'})
                    trans_tag.string = translated
                    tag.insert_after(trans_tag)

                    # 给原文标签加 class
                    if 'original' not in tag.get('class', []):
                        existing = tag.get('class', [])
                        existing.append('original')
                        tag['class'] = existing

            # 确保有 html 结构
            html_content = str(soup)
            if not html_content.startswith('<?xml') and not html_content.startswith('<html'):
                html_content = f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title></title></head><body>{html_content}</body></html>'

            # 注入双语 CSS 链接
            html_content = html_content.replace('</head>',
                                                '<link rel="stylesheet" type="text/css" href="bilingual.css"/></head>')

            # 创建新章节
            file_name = chapter.get_name()
            chapter_title = self._get_chapter_title(soup) or f"Chapter {ch_idx + 1}"

            new_chapter = epub.EpubHtml(
                title=chapter_title,
                file_name=file_name,
                content=html_content.encode('utf-8')
            )
            new_chapter.add_item(css_item)

            bilingual_book.add_item(new_chapter)
            spine_items.append(new_chapter)
            toc_items.append(new_chapter)

        # 设置目录和书脊
        bilingual_book.toc = toc_items
        bilingual_book.add_item(epub.EpubNcx())
        bilingual_book.add_item(epub.EpubNav())
        bilingual_book.spine = ['nav'] + spine_items

        # 写入
        epub.write_epub(output_path, bilingual_book)
        return output_path

    @staticmethod
    def _get_chapter_title(soup) -> str:
        """从 HTML 中提取章节标题"""
        for tag in soup.find_all(['h1', 'h2', 'h3']):
            text = tag.get_text(strip=True)
            if text and len(text) < 100:
                return text
        return ""
