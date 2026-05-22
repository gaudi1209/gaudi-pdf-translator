"""
PDF 重建模块 - 根据翻译结果重建 PDF
使用 insert_textbox 实现自动换行排版
使用微软雅黑字体支持中英文混排
"""
import fitz
import os
import re
from typing import List, Optional
from core.pdf_parser import PageInfo


class PDFRebuilder:
    """PDF 重建器 - 使用微软雅黑字体实现中英文混排"""

    # 微软雅黑字体路径
    FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
    FONT_NAME = "F0"  # 嵌入字体的名称

    def __init__(self, output_path: str):
        self.output_path = output_path
        self.font_path = self._find_font()

    def _find_font(self) -> Optional[str]:
        """查找可用字体"""
        fonts = [
            "C:/Windows/Fonts/msyh.ttc",    # 微软雅黑
            "C:/Windows/Fonts/simhei.ttf",  # 黑体
            "C:/Windows/Fonts/simsun.ttc",  # 宋体
        ]
        for path in fonts:
            if os.path.exists(path):
                print(f"使用字体: {path}")
                return path
        return None

    def _preprocess_text(self, text: str) -> str:
        """预处理文本，只在列表项前保留换行"""
        if not text:
            return text

        # 1. 保护列表项前的换行（换行符后跟 数字. + 内容）
        PLACEHOLDER = "<<NEWLINE>>"
        text = re.sub(r'\n(\d+\.)(?=[\s\u4e00-\u9fffa-zA-Z])', PLACEHOLDER + r'\1', text)

        # 2. 统一所有空白字符为普通空格
        text = re.sub(r'[\s\u00a0]+', ' ', text)

        # 3. 恢复列表项前的换行
        text = text.replace(PLACEHOLDER, '\n')

        # 4. 在其他列表项前添加换行（空格 + 数字. + 内容）
        text = re.sub(r' (\d+\.)(?=[\s\u4e00-\u9fffa-zA-Z])', r'\n\1', text)

        # 5. 移除中文和英文/数字之间的空格
        text = re.sub(r'([\u4e00-\u9fff]) +([a-zA-Z0-9])', r'\1\2', text)
        text = re.sub(r'([a-zA-Z0-9]) +([\u4e00-\u9fff])', r'\1\2', text)

        # 6. 移除中文之间的空格
        text = re.sub(r'([\u4e00-\u9fff]) +([\u4e00-\u9fff])', r'\1\2', text)

        # 7. 确保最多只有1个空格
        text = re.sub(r' {2,}', ' ', text)

        return text.strip()

    def rebuild_from_original(self, original_pdf: str, pages_info: List[PageInfo]) -> str:
        """基于原始 PDF 重建，保持矢量图，自动换行排版"""
        import tempfile
        import os

        # 直接打开原PDF，不预先转换（保持矢量图）
        doc = fitz.open(original_pdf)

        for page_num, page_info in enumerate(pages_info):
            if page_num >= len(doc):
                break

            page = doc[page_num]

            # 为当前页嵌入字体
            fontname = "china-s"  # 默认字体
            if self.font_path:
                try:
                    xref = page.insert_font(fontname=self.FONT_NAME, fontfile=self.font_path)
                    if xref:
                        fontname = self.FONT_NAME
                except Exception as e:
                    print(f"嵌入字体失败: {e}")

            blocks_to_translate = [
                block for block in page_info.blocks
                if block.should_translate and block.translated_text
            ]

            if not blocks_to_translate:
                continue

            blocks_to_translate.sort(key=lambda b: (b.bbox[1], b.bbox[0]))

            # 使用redact方法覆盖原文
            redacted_blocks = []
            for block in blocks_to_translate:
                rect = fitz.Rect(block.bbox)
                try:
                    page.add_redact_annot(rect, fill=(1, 1, 1))
                    redacted_blocks.append(block)
                except Exception as e:
                    print(f"添加涂黑失败 (page {page_num}, block {block.id}): {e}")
                    # 如果redact失败，使用白色矩形
                    try:
                        page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1))
                        redacted_blocks.append(block)
                    except Exception as e2:
                        print(f"跳过 block {block.id}: {e2}")
                        continue

            # 应用涂黑
            try:
                page.apply_redactions()
            except Exception as e:
                print(f"应用涂黑失败 (page {page_num}): {e}")

            # 插入翻译文本
            for block in redacted_blocks:
                rect = fitz.Rect(block.bbox)

                processed_text = self._preprocess_text(block.translated_text)
                if not processed_text:
                    continue

                font_size, line_height = self._calculate_font_and_lineheight(
                    processed_text,
                    rect.width,
                    rect.height,
                    block.font_info.get("size", 11)
                )

                try:
                    # 使用嵌入字体时需要同时传递 fontfile
                    if self.font_path and fontname == self.FONT_NAME:
                        result = page.insert_textbox(
                            rect,
                            processed_text,
                            fontsize=font_size,
                            fontname=fontname,
                            fontfile=self.font_path,
                            color=(0, 0, 0),
                            align=fitz.TEXT_ALIGN_LEFT,
                            lineheight=line_height
                        )
                    else:
                        result = page.insert_textbox(
                            rect,
                            processed_text,
                            fontsize=font_size,
                            fontname=fontname,
                            color=(0, 0, 0),
                            align=fitz.TEXT_ALIGN_LEFT,
                            lineheight=line_height
                        )

                    if result < 0:
                        smaller_font = max(6, font_size * 0.85)
                        if self.font_path and fontname == self.FONT_NAME:
                            page.insert_textbox(
                                rect,
                                processed_text,
                                fontsize=smaller_font,
                                fontname=fontname,
                                fontfile=self.font_path,
                                color=(0, 0, 0),
                                align=fitz.TEXT_ALIGN_LEFT,
                                lineheight=line_height
                            )
                        else:
                            page.insert_textbox(
                                rect,
                                processed_text,
                                fontsize=smaller_font,
                                fontname=fontname,
                                color=(0, 0, 0),
                                align=fitz.TEXT_ALIGN_LEFT,
                                lineheight=line_height
                            )

                except Exception as e:
                    print(f"插入文本失败 (block {block.id}): {e}")

        # 保存时使用更高的 garbage 级别处理颜色空间问题
        try:
            doc.save(self.output_path, garbage=4, deflate=True)
        except Exception as e:
            print(f"保存失败，尝试简化保存: {e}")
            doc.save(self.output_path, deflate=True)
        doc.close()

        return self.output_path

    def _calculate_font_and_lineheight(self, text: str, width: float, height: float,
                                        original_size: float) -> tuple:
        """计算合适的字体大小和行距 - 尽量填满文本框"""
        if not text or width <= 0 or height <= 0:
            return 10, 1.2

        char_count = len(text)
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        chinese_ratio = chinese_chars / max(char_count, 1)

        base_size = original_size
        line_height_ratio = 1.15

        avg_char_width = base_size * (chinese_ratio * 1.0 + (1 - chinese_ratio) * 0.55)
        text_width = char_count * avg_char_width

        line_height = base_size * line_height_ratio
        max_lines = max(1, int(height / line_height))

        width_per_line = width * max_lines

        if text_width > width_per_line:
            base_size *= width_per_line / text_width * 0.95

        new_line_height = base_size * line_height_ratio
        new_text_width = char_count * base_size * (chinese_ratio * 1.0 + (1 - chinese_ratio) * 0.55)
        new_lines = max(1, (new_text_width / width) + 0.5)
        needed_height = new_lines * new_line_height

        if needed_height > height:
            base_size *= height / needed_height * 0.95

        final_size = max(8, min(base_size, original_size))
        return final_size, line_height_ratio


class BilingualPDFRebuilder:
    """双语对照 PDF 重建器"""

    def __init__(self, output_path: str):
        self.output_path = output_path

    def create_bilingual(self, original_pdf: str, translated_pdf: str) -> str:
        """创建双语对照 PDF（上下排列）"""
        src_doc = fitz.open(original_pdf)
        trans_doc = fitz.open(translated_pdf)
        out_doc = fitz.open()

        for page_num in range(len(src_doc)):
            src_page = src_doc[page_num]
            trans_page = trans_doc[page_num] if page_num < len(trans_doc) else src_page

            new_width = src_page.rect.width
            new_height = src_page.rect.height * 2 + 20
            new_page = out_doc.new_page(width=new_width, height=new_height)

            top_rect = fitz.Rect(0, 0, src_page.rect.width, src_page.rect.height)
            new_page.show_pdf_page(top_rect, src_doc, page_num)

            bottom_rect = fitz.Rect(
                0, src_page.rect.height + 20,
                src_page.rect.width, new_height
            )
            new_page.show_pdf_page(bottom_rect, trans_doc, page_num)

        src_doc.close()
        trans_doc.close()
        out_doc.save(self.output_path)
        out_doc.close()
        return self.output_path

    def create_interleaved(self, original_pdf: str, translated_pdf: str,
                           skip_pages: List[int] = None) -> str:
        """创建交错双语 PDF（一页原文接一页译文）

        对于跳过翻译的页面（目录、参考文献等），只显示原文一次。
        通过添加空白页确保双页展示时左右对译。

        Args:
            original_pdf: 原始 PDF 文件路径
            translated_pdf: 翻译后的 PDF 文件路径
            skip_pages: 跳过翻译的页面索引列表（0-based），如果为None则自动检测

        Returns:
            输出文件路径
        """
        src_doc = fitz.open(original_pdf)
        trans_doc = fitz.open(translated_pdf)
        out_doc = fitz.open()

        src_pages = len(src_doc)
        trans_pages = len(trans_doc)
        total_pages = max(src_pages, trans_pages)

        # 如果没有提供跳过页面列表，自动检测（通过检查译文页是否有中文）
        if skip_pages is None:
            skip_pages = self._detect_skip_pages(trans_doc)
            print(f"自动检测跳过页面: {len(skip_pages)} 页")

        print(f"创建交错双语 PDF: 原文 {src_pages} 页, 译文 {trans_pages} 页, 跳过 {len(skip_pages)} 页")

        # 获取参考页面尺寸（用于创建空白页）
        ref_width = src_doc[0].rect.width if src_pages > 0 else 595
        ref_height = src_doc[0].rect.height if src_pages > 0 else 842

        # 区域跟踪：用于确保每个区域结束时的页数为偶数
        current_section_start = 0
        current_section_is_skip = None  # 当前区域类型

        def add_blank_page():
            """添加空白页"""
            blank_page = out_doc.new_page(width=ref_width, height=ref_height)
            # 添加淡灰色文字提示
            blank_page.insert_text(
                point=(ref_width / 2 - 30, ref_height / 2),
                text="[ 空白页 ]",
                fontsize=12,
                color=(0.8, 0.8, 0.8)
            )

        def flush_section(end_of_section):
            """处理区域结束，确保页数为偶数"""
            nonlocal current_section_start, current_section_is_skip
            if current_section_is_skip is None:
                return

            section_pages = end_of_section - current_section_start
            # 如果跳过区域的页数是奇数，添加空白页使其变为偶数
            if current_section_is_skip and section_pages % 2 == 1:
                add_blank_page()
                print(f"  区域 {current_section_start}-{end_of_section-1} 为奇数页，添加空白页")

            current_section_start = end_of_section

        for page_num in range(total_pages):
            is_skip = page_num in skip_pages

            # 检测区域变化
            if current_section_is_skip is None:
                current_section_is_skip = is_skip
                current_section_start = 0
            elif current_section_is_skip != is_skip:
                # 区域变化，刷新上一个区域
                flush_section(page_num)
                current_section_is_skip = is_skip
                current_section_start = page_num

            if is_skip:
                # 跳过翻译的页面：只添加原文（一次）
                if page_num < src_pages:
                    src_page = src_doc[page_num]
                    new_page = out_doc.new_page(
                        width=src_page.rect.width,
                        height=src_page.rect.height
                    )
                    new_page.show_pdf_page(new_page.rect, src_doc, page_num)
            else:
                # 正文页面：添加原文+译文
                if page_num < src_pages:
                    src_page = src_doc[page_num]
                    new_page = out_doc.new_page(
                        width=src_page.rect.width,
                        height=src_page.rect.height
                    )
                    new_page.show_pdf_page(new_page.rect, src_doc, page_num)

                if page_num < trans_pages:
                    trans_page = trans_doc[page_num]
                    new_page = out_doc.new_page(
                        width=trans_page.rect.width,
                        height=trans_page.rect.height
                    )
                    new_page.show_pdf_page(new_page.rect, trans_doc, page_num)

        # 刷新最后一个区域
        flush_section(total_pages)

        src_doc.close()
        trans_doc.close()
        out_doc.save(self.output_path, deflate=True)
        out_doc.close()

        print(f"交错双语 PDF 已保存: {self.output_path}")
        return self.output_path

    def _detect_skip_pages(self, trans_doc) -> List[int]:
        """检测跳过翻译的页面（通过检查是否有中文内容）

        Args:
            trans_doc: 翻译后的 PDF 文档

        Returns:
            跳过的页面索引列表
        """
        skip_pages = []

        for page_num in range(len(trans_doc)):
            page = trans_doc[page_num]
            text = page.get_text()

            if not text.strip():
                # 空白页面，跳过
                skip_pages.append(page_num)
                continue

            # 检查是否有中文字符
            has_chinese = any('\u4e00' <= c <= '\u9fff' for c in text)

            if not has_chinese:
                # 没有中文，说明是跳过翻译的页面
                skip_pages.append(page_num)

        return skip_pages


def rebuild_pdf(original_pdf: str, pages_info: List[PageInfo], output_path: str) -> str:
    """便捷函数：重建 PDF"""
    rebuilder = PDFRebuilder(output_path)
    return rebuilder.rebuild_from_original(original_pdf, pages_info)
