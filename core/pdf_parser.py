"""
PDF 解析模块 - 提取文本块、图片、公式位置
按 block（段落）级别提取
"""
import fitz  # PyMuPDF
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
import re


class BlockType(Enum):
    TEXT = "text"
    FORMULA = "formula"
    FIGURE = "figure"
    TABLE = "table"
    HEADER = "header"
    FOOTER = "footer"
    CODE = "code"  # 代码块，不翻译
    REFERENCES = "references"  # 附录、注释、引文、文献，不翻译


@dataclass
class FormulaSpan:
    """行内公式位置"""
    start: int      # 在 text 中的起始位置
    end: int        # 结束位置
    text: str       # 公式原文


@dataclass
class TextBlock:
    """文本块数据结构"""
    id: str
    block_type: BlockType
    text: str
    original_text: str = ""
    translated_text: str = ""
    bbox: Tuple[float, float, float, float] = (0, 0, 0, 0)
    page_num: int = 0
    font_info: Dict = field(default_factory=dict)
    should_translate: bool = True
    image_data: Optional[bytes] = None
    formula_spans: List['FormulaSpan'] = field(default_factory=list)


@dataclass
class PageInfo:
    """页面信息"""
    page_num: int
    width: float
    height: float
    blocks: List[TextBlock] = field(default_factory=list)
    chapter_title: Optional[str] = None  # 章节标题（如果有）


@dataclass
class ChapterInfo:
    """章节信息"""
    title: str
    start_page: int
    end_page: int
    page_count: int


class FormulaDetector:
    """公式检测器 - 支持多种数学字体检测"""

    # LaTeX Computer Modern 数学字体
    MATH_FONT_PREFIXES = [
        'cmmi',   # Computer Modern Math Italic
        'cmsy',   # Computer Modern Symbol
        'cmex',   # Computer Modern Extended (积分符号等)
        'cmr',    # Computer Modern Roman (数学模式)
        'cmbx',   # Computer Modern Bold
        'cmti',   # Computer Modern Text Italic (数学模式)
        'msam',   # AMS Symbol A
        'msbm',   # AMS Symbol B
        'eufm',   # Euler Fraktur
        'euex',   # Euler Extended
    ]

    # 其他数学字体关键词
    MATH_FONT_KEYWORDS = [
        'symbol', 'mt extra', 'mt symbol', 'math', 'cambria math',
        'stix', 'xits', 'latin modern math', 'tex gyre',
    ]

    # 完整匹配的数学字体名称（非LaTeX）
    MATH_FONT_NAMES = [
        'symbolmt',        # Symbol MT (MathType)
        'mt-extra',        # MT Extra (MathType)
        'euclidsymbol',    # Euclid Symbol
        'euclidextra',     # Euclid Extra
        'euclidmathone',   # Euclid Math One
        'euclidmathtwo',   # Euclid Math Two
        'stixgeneral-italic',  # STIX General Italic
        'stixgeneral-bold',    # STIX General Bold
        'stixmath',        # STIX Math
        'minion-italic',   # Minion Italic (常用于变量)
        'minionpro-it',    # Minion Pro Italic
        'timesnewromanps-italicmt',  # Times 斜体（数学模式）
    ]

    def __init__(self):
        self.latex_patterns = [
            r'\\frac\{', r'\\sum', r'\\int', r'\\sqrt\{',
            r'\\alpha', r'\\beta', r'\\gamma', r'\\delta',
            r'\\pi', r'\\infty', r'\\partial', r'\\nabla',
            r'\\left', r'\\right', r'\\cdot', r'\\times',
        ]
        self.math_unicode = set('∑∏∫∬∮√∛∜∞∂∇'
                                'αβγδεζηθικλμνξπρστυφχψω'
                                'ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ'
                                '∈∉⊂⊃⊆⊇∪∩∅∀∃∄±∓×÷≠≈≡≤≥→←↔⇒⇐⇔')
        self.math_expr_patterns = [
            r'\$[^$]+\$', r'\$\$[^$]+\$\$',
            r'[a-zA-Z]\^\{[^}]+\}', r'[a-zA-Z]_\{[^}]+\}',
            r'\d+\s*[+\-*/=]\s*\d+',
        ]

    def is_math_font(self, font: str) -> bool:
        """检测是否为数学字体"""
        if not font:
            return False
        font_lower = font.lower().replace(' ', '-')

        # 检查 LaTeX CM 字体前缀
        for prefix in self.MATH_FONT_PREFIXES:
            if font_lower.startswith(prefix):
                return True

        # 检查其他数学字体关键词
        for keyword in self.MATH_FONT_KEYWORDS:
            if keyword in font_lower:
                return True

        # 检查完整匹配的数学字体名称
        for name in self.MATH_FONT_NAMES:
            if font_lower == name or font_lower.startswith(name):
                return True

        return False

    def is_formula(self, text: str, font: str = "") -> bool:
        if not text:
            return False

        # 优先检测数学字体
        if self.is_math_font(font):
            return True

        for pattern in self.latex_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        symbol_count = sum(1 for c in text if c in self.math_unicode)
        if len(text) > 0 and symbol_count / len(text) > 0.15:
            return True
        for pattern in self.math_expr_patterns:
            if re.search(pattern, text):
                return True

        return False

    def is_formula_derivation(self, text: str) -> bool:
        """检测是否为独立的公式推导段落（非常严格）

        只有当段落几乎完全是数学推导时才返回 True
        文中嵌入的公式不会被检测，保持翻译

        Args:
            text: 文本内容

        Returns:
            bool: 是否为独立的公式推导段落
        """
        if not text or len(text) < 20:
            return False

        score = 0

        # 1. 检查数学符号密度（需要非常高）
        math_operators = set('=+-×÷±∓·*/<>≤≥≠≈≡→←↔⇒⇐⇔∴∵')
        operator_count = sum(1 for c in text if c in math_operators)
        operator_density = operator_count / max(len(text), 1)
        if operator_density > 0.15:  # 非常高的密度
            score += 3
        elif operator_density > 0.10:
            score += 2

        # 2. 检查等号数量（需要很多）
        equal_count = text.count('=')
        if equal_count >= 5:
            score += 3
        elif equal_count >= 3:
            score += 2

        # 3. 检查 Unicode 数学符号（需要很多）
        unicode_math_count = sum(1 for c in text if c in self.math_unicode)
        if unicode_math_count >= 10:
            score += 3
        elif unicode_math_count >= 5:
            score += 2

        # 4. 检查是否包含正常的英文句子（有正常句子则不太可能是纯公式）
        # 正常句子有大小写字母和空格
        words = re.findall(r'[A-Za-z]{3,}', text)  # 3个字母以上的单词
        if len(words) > 5:  # 如果有很多英文单词，可能是普通文本
            score -= 2

        # 5. 检查推导符号
        derivation_symbols = ['→', '⇒', '⇐', '∴', '∵', '⟹', '⟸']
        if sum(1 for s in derivation_symbols if s in text) >= 2:
            score += 2

        # 6. 检查是否主要是数学内容（很少有完整句子）
        sentences = re.split(r'[.!?]\s+', text)
        if len(sentences) == 1 and len(text) > 50:  # 一个长"句子"可能是公式
            score += 1

        # 7. 检查 LaTeX 标记
        latex_markers = ['\\frac', '\\sum', '\\int', '\\sqrt', '\\partial']
        latex_count = sum(1 for m in latex_markers if m in text)
        if latex_count >= 3:
            score += 3
        elif latex_count >= 1:
            score += 1

        # 阈值提高到 8，只检测非常明显的公式推导
        return score >= 8


class CodeDetector:
    """代码块检测器 - 识别大段程序代码"""

    # 等宽字体关键词
    MONOSPACE_FONTS = [
        'courier', 'consolas', 'monaco', 'menlo', 'mono',
        'code', 'fixed', 'typewriter', 'mono-spaced',
        'dejavu sans mono', 'liberation mono', 'source code',
        'fira code', 'jetbrains', 'hack', 'ubuntu mono'
    ]

    # 编程语言关键字
    PROGRAMMING_KEYWORDS = [
        # 通用
        'function', 'def', 'class', 'import', 'from', 'return', 'if', 'else',
        'for', 'while', 'try', 'except', 'finally', 'with', 'as', 'async', 'await',
        'const', 'let', 'var', 'async', 'await', 'yield', 'lambda', 'fn',
        # Python
        'print', 'self', 'None', 'True', 'False', 'elif', 'pass', 'break', 'continue',
        # JavaScript/TypeScript
        'console', 'log', 'const', 'let', 'var', 'require', 'export', 'default',
        # Java/C/C++
        'public', 'private', 'protected', 'static', 'void', 'int', 'string',
        'namespace', 'using', 'include', 'printf', 'scanf', 'malloc', 'free',
        # Shell
        'echo', 'grep', 'awk', 'sed', 'chmod', 'bash', 'shell',
    ]

    # 代码特征正则
    CODE_PATTERNS = [
        r'^\s*\d+\s+[a-zA-Z]',           # 行号开头
        r'^\s*(def|function|class|public|private)\s+',  # 函数/类定义
        r'^\s*(import|from|include|using|require)\s+',  # 导入语句
        r'^\s*(if|else|for|while|switch|case)\s*[\(\{]', # 控制语句
        r'^\s*\/\/\s*',                   # 单行注释
        r'^\s*\/\*',                      # 多行注释开始
        r'^\s*#\s*(include|define|import)',  # 预处理指令
        r'\{[\s\n]*\}',                   # 空代码块
        r';\s*$',                         # 分号结尾
        r'[\(\)\[\]\{\}]',                # 括号
        r'->\s*\w+',                      # 箭头操作符
        r'=>\s*[\{\(]?',                  # 箭头函数
        r'::\s*\w+',                      # 作用域操作符
    ]

    def __init__(self):
        self.keyword_set = set(self.PROGRAMMING_KEYWORDS)

    def is_code_block(self, text: str, font: str = "", lines: list = None) -> bool:
        """检测是否为代码块

        Args:
            text: 文本内容
            font: 字体名称
            lines: 原始行列表（用于更精确的检测）

        Returns:
            bool: 是否为代码块
        """
        if not text or len(text.strip()) < 20:
            return False

        text_lower = text.lower()
        score = 0

        # 1. 检查是否使用等宽字体（强信号）
        if font:
            font_lower = font.lower()
            for mono_font in self.MONOSPACE_FONTS:
                if mono_font in font_lower:
                    score += 3
                    break

        # 2. 检查代码特征模式
        code_pattern_matches = 0
        for pattern in self.CODE_PATTERNS:
            if re.search(pattern, text, re.MULTILINE):
                code_pattern_matches += 1
        if code_pattern_matches >= 2:
            score += 2
        elif code_pattern_matches >= 1:
            score += 1

        # 3. 检查编程关键字密度
        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', text_lower)
        if words:
            keyword_count = sum(1 for w in words if w in self.keyword_set)
            keyword_ratio = keyword_count / len(words)
            if keyword_ratio > 0.15:
                score += 2
            elif keyword_ratio > 0.08:
                score += 1

        # 4. 检查缩进特征（代码通常有多级缩进）
        if lines:
            indented_lines = sum(1 for line in lines if line.startswith('  ') or line.startswith('\t'))
            if len(lines) > 3 and indented_lines / len(lines) > 0.3:
                score += 2

        # 5. 检查括号密度
        bracket_count = text.count('(') + text.count(')') + text.count('{') + text.count('}')
        bracket_density = bracket_count / max(len(text), 1)
        if bracket_density > 0.05:
            score += 2
        elif bracket_density > 0.02:
            score += 1

        # 6. 检查行特征（代码通常有很多短行）
        text_lines = text.split('\n')
        if len(text_lines) >= 3:
            avg_line_len = sum(len(line) for line in text_lines) / len(text_lines)
            if avg_line_len < 50:  # 代码行通常较短
                score += 1

        # 7. 检查特殊符号
        special_chars = sum(1 for c in text if c in '[]{}();:.,=<>!&|+-*/%')
        if special_chars / max(len(text), 1) > 0.08:
            score += 1

        # 阈值判断 - 暂时禁用代码块检测
        return score >= 100  # 几乎不可能达到，相当于禁用


class SectionDetector:
    """特殊章节检测器 - 识别目录、参考文献、附录等"""

    # 永久跳过的章节（文档末尾）
    # 注意：不匹配章内附录（如 Appendix 2A），只匹配文档末尾的附录（如 Appendix A）
    # 注意：Acknowledgements 不在此列表，因为它通常出现在文档前面，不应触发永久跳过
    SKIP_SECTIONS_EN = [
        r'^appendix(es)?(\s+[a-z]+)?$',         # Appendix, Appendix A（不匹配 Appendix 2A）
        r'^appendices$',                         # Appendices
        r'^notes?(\s+to\s+chapter\s*\d+)?$',    # Notes
        r'^citations?$',                         # Citations
        r'^references?$',                        # References
        r'^bibliography$',                       # Bibliography
        r'^further\s+reading$',                  # Further Reading
        r'^suggested\s+reading$',                # Suggested Reading
        # r'^acknowledgements?$',               # 移除：不应触发永久跳过
        r'^index$',                              # Index
        r'^glossary$',                           # Glossary
    ]

    SKIP_SECTIONS_ZH = [
        r'^附录\s*[a-z0-9\u4e00-\u9fff]*$',      # 附录
        r'^注释$',                                # 注释
        r'^参考文献$',                            # 参考文献
        r'^文献$',                                # 文献
        r'^书目$',                                # 书目
        r'^索引$',                                # 索引
        r'^术语表$',                              # 术语表
        r'^致谢$',                                # 致谢
    ]

    # 目录章节
    TOC_SECTIONS_EN = [
        r'^contents?$',
        r'^table\s+of\s+contents?$',
        r'^list\s+of\s+(figures|tables|abbreviations|symbols)$',
    ]

    TOC_SECTIONS_ZH = [
        r'^目录$',
        r'^内容提要$',
        r'^图表目录$',
    ]

    def __init__(self):
        self.patterns_en = [re.compile(p, re.IGNORECASE) for p in self.SKIP_SECTIONS_EN]
        self.patterns_zh = [re.compile(p) for p in self.SKIP_SECTIONS_ZH]
        self.toc_patterns_en = [re.compile(p, re.IGNORECASE) for p in self.TOC_SECTIONS_EN]
        self.toc_patterns_zh = [re.compile(p) for p in self.TOC_SECTIONS_ZH]

    def is_skip_section(self, title: str) -> bool:
        """检测是否为需要跳过的章节（参考文献、附录等）"""
        if not title:
            return False

        title = title.strip()
        title = re.sub(r'\s*\d+\s*$', '', title)
        title = re.sub(r'\s*\.\.\..*$', '', title)

        for pattern in self.patterns_en:
            if pattern.match(title):
                return True
        for pattern in self.patterns_zh:
            if pattern.match(title):
                return True

        return False

    def is_toc_section(self, title: str) -> bool:
        """检测是否为目录章节"""
        if not title:
            return False

        title = title.strip()
        title = re.sub(r'\s*\d+\s*$', '', title)

        for pattern in self.toc_patterns_en:
            if pattern.match(title):
                return True
        for pattern in self.toc_patterns_zh:
            if pattern.match(title):
                return True

        return False

    def is_toc_page(self, text: str) -> bool:
        """检测页面是否为目录页（基于内容特征）"""
        if not text:
            return False

        # 特征1: 大量的点号+页码模式（目录特有）
        dots_pattern = len(re.findall(r'\.{2,}\s*\d+', text))
        if dots_pattern > 5:
            return True

        # 特征2: 章节标题+页码模式
        chapter_pattern = len(re.findall(r'(Chapter|第\s*\d+\s*章|Section)\s*\d+[^\n]*\s*\d+', text, re.IGNORECASE))
        if chapter_pattern > 3:
            return True

        # 特征3: 检测 "Contents" 作为独立标题（行首或单独一行）
        # 注意：要排除版权页中的 "content" 普通用法
        lines = text.split('\n')
        for line in lines:
            line_stripped = line.strip()
            # 目录标题通常是单独一行的 "Contents" 或 "Table of Contents"
            if re.match(r'^(Table\s+of\s+)?Contents$', line_stripped, re.IGNORECASE):
                return True

        return False


class PDFParser:
    """PDF 解析器 - 按 block（段落）级别提取"""

    # 章节标题模式
    CHAPTER_PATTERNS = [
        r'^(\d+\.?\s+.+)$',           # "1. Introduction" 或 "1 Introduction"
        r'^(Chapter\s+\d+.*)$',        # "Chapter 1: ..."
        r'^(第[一二三四五六七八九十\d]+[章节篇].*)$',  # 中文章节
        r'^([A-Z][A-Z\s]{5,})$',       # 全大写标题
    ]

    def __init__(self, pdf_path: str):
        self.doc = fitz.open(pdf_path)
        self.pages: List[PageInfo] = []
        self.formula_detector = FormulaDetector()
        self.code_detector = CodeDetector()
        self.section_detector = SectionDetector()
        self.chapters: List[ChapterInfo] = []
        self._avg_font_size = 12  # 平均字体大小
        self._in_skip_section = False  # 是否进入参考文献/附录区域
        self._in_toc_section = False   # 是否进入目录区域
        self._non_toc_page_count = 0   # 连续非目录页计数

    # 前置章节（不应触发退出目录）
    FRONT_SECTIONS = [
        'dedication', 'foreword', 'preface', 'acknowledgments', 'acknowledgements',
        'about the author', 'about the authors', 'author biography',
        '致谢', '前言', '序言', '作者简介',
    ]

    def _is_real_chapter_title(self, text: str, font_size: float) -> bool:
        """判断是否是真正的章节标题（而非目录条目）

        真正的章节标题特征：
        1. 字体明显大于平均字体
        2. 不包含页码
        3. 符合章节命名模式
        4. 不是前置章节（Dedication, Foreword, Preface 等）
        """
        if not text:
            return False

        text_stripped = text.strip()

        # 检查是否包含点号+页码（目录条目特征）
        if re.search(r'\.{2,}\s*\d+$', text_stripped):
            return False

        # 检查是否只是数字（页码）
        if re.match(r'^\d+$', text_stripped):
            return False

        # 检查是否是前置章节（这些不应触发退出目录）
        text_lower = text_stripped.lower()
        for section in self.FRONT_SECTIONS:
            if text_lower == section or text_lower.startswith(section + ' to'):
                return False

        # 检查字体是否足够大（真正的章节标题通常比正文大很多）
        if font_size < self._avg_font_size * 1.3:
            return False

        # 检查是否符合章节模式
        # 注意：不使用 IGNORECASE，因为全大写模式需要区分大小写
        chapter_patterns_case_sensitive = [
            r'^([A-Z][A-Z\s]{5,})$',      # 全大写标题（严格匹配）
        ]
        chapter_patterns_ignore_case = [
            r'^(\d+\.?\s+\w+)',           # "1. Introduction"
            r'^(Chapter\s+\d+)',          # "Chapter 1"
            r'^(第[一二三四五六七八九十\d]+[章节篇])',  # 中文章节
        ]

        # 先检查区分大小写的模式
        for pattern in chapter_patterns_case_sensitive:
            if re.match(pattern, text_stripped):
                return True

        # 再检查忽略大小写的模式
        for pattern in chapter_patterns_ignore_case:
            if re.match(pattern, text_stripped, re.IGNORECASE):
                return True

        return False

    def parse(self) -> List[PageInfo]:
        # 第一遍：解析所有页面，计算平均字体大小
        font_sizes = []
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            page_info = self._parse_page(page, page_num)
            self.pages.append(page_info)

            # 收集字体大小
            for block in page_info.blocks:
                if block.font_info.get("size"):
                    font_sizes.append(block.font_info["size"])

        # 计算平均字体大小
        if font_sizes:
            self._avg_font_size = sum(font_sizes) / len(font_sizes)

        # 检测章节边界
        self._detect_chapters()

        return self.pages

    def _detect_chapters(self):
        """检测章节边界"""
        self.chapters = []
        current_chapter_start = 0
        current_chapter_title = "开始"

        for page_num, page_info in enumerate(self.pages):
            # 查找页面第一个大字体标题
            chapter_title = None
            for block in page_info.blocks:
                if block.block_type == BlockType.HEADER:
                    text = block.text.strip()
                    font_size = block.font_info.get("size", 12)

                    # 检查是否符合章节模式
                    is_chapter = False
                    for pattern in self.CHAPTER_PATTERNS:
                        if re.match(pattern, text, re.IGNORECASE):
                            is_chapter = True
                            break

                    # 或者字体明显大于平均（1.5倍以上）
                    if not is_chapter and font_size > self._avg_font_size * 1.5:
                        # 检查是否像标题（较短，不超过100字符）
                        if len(text) < 100 and len(text) > 3:
                            is_chapter = True

                    if is_chapter:
                        chapter_title = text[:50]  # 截断过长的标题
                        break

            # 如果找到新章节标题
            if chapter_title and page_num > current_chapter_start:
                # 保存上一个章节
                self.chapters.append(ChapterInfo(
                    title=current_chapter_title,
                    start_page=current_chapter_start,
                    end_page=page_num - 1,
                    page_count=page_num - current_chapter_start
                ))
                current_chapter_start = page_num
                current_chapter_title = chapter_title
                page_info.chapter_title = chapter_title

        # 保存最后一个章节
        if self.pages:
            self.chapters.append(ChapterInfo(
                title=current_chapter_title,
                start_page=current_chapter_start,
                end_page=len(self.pages) - 1,
                page_count=len(self.pages) - current_chapter_start
            ))

        # 如果没有检测到章节，将整个文档作为一个章节
        if not self.chapters and self.pages:
            self.chapters.append(ChapterInfo(
                title="全文",
                start_page=0,
                end_page=len(self.pages) - 1,
                page_count=len(self.pages)
            ))

        print(f"检测到 {len(self.chapters)} 个章节:")
        for ch in self.chapters:
            print(f"  - {ch.title}: 第{ch.start_page + 1}-{ch.end_page + 1}页 ({ch.page_count}页)")

        # 统计块类型
        type_counts = {}
        translate_counts = {"yes": 0, "no": 0}
        for page_info in self.pages:
            for block in page_info.blocks:
                bt = block.block_type.value
                type_counts[bt] = type_counts.get(bt, 0) + 1
                if block.should_translate:
                    translate_counts["yes"] += 1
                else:
                    translate_counts["no"] += 1

        print(f"\n块类型统计:")
        for bt, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"  {bt}: {count}")
        print(f"\n翻译状态:")
        print(f"  需翻译: {translate_counts['yes']}")
        print(f"  跳过: {translate_counts['no']}")

    @staticmethod
    def _is_inside_figure(bbox, figure_regions, overlap_threshold=0.6):
        """检查文本块是否在图片区域内（重叠超过阈值则跳过）"""
        if not figure_regions or not bbox:
            return False
        bx0, by0, bx1, by1 = bbox
        b_area = max(0, (bx1 - bx0) * (by1 - by0))
        if b_area <= 0:
            return False

        for fx0, fy0, fx1, fy1 in figure_regions:
            # 计算重叠区域
            ox0 = max(bx0, fx0)
            oy0 = max(by0, fy0)
            ox1 = min(bx1, fx1)
            oy1 = min(by1, fy1)
            o_area = max(0, (ox1 - ox0) * (oy1 - oy0))
            if o_area / b_area >= overlap_threshold:
                return True
        return False

    def _parse_page(self, page: fitz.Page, page_num: int) -> PageInfo:
        """解析单页 - 按 block 创建 TextBlock"""
        blocks = []

        # 检查是否为目录页（基于页面内容特征）
        page_text = page.get_text()
        is_toc_page = self.section_detector.is_toc_page(page_text)

        if is_toc_page:
            self._in_toc_section = True
            self._non_toc_page_count = 0
        elif self._in_toc_section:
            # 已经在目录区域，检查是否应该退出
            # 如果页面有大量正文内容（长文本且不含目录标记），可能是正文开始
            text_lower = page_text.lower()
            has_contents = 'contents' in text_lower or 'table of contents' in text_lower

            if not has_contents and len(page_text) > 1500:
                self._non_toc_page_count += 1
                # 连续2页非目录内容，退出目录区域
                if self._non_toc_page_count >= 2:
                    print(f"  页{page_num + 1}: 退出目录区域（连续{self._non_toc_page_count}页非目录内容）")
                    self._in_toc_section = False
            else:
                self._non_toc_page_count = 0

        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        # 收集图片区域（用于跳过图纸中的文字）
        figure_regions = []
        for block in text_dict.get("blocks", []):
            if block.get("type") == 1:  # 图片块
                bbox = block.get("bbox", (0, 0, 0, 0))
                figure_regions.append(bbox)
        # 也从 page images 收集
        image_list = page.get_images(full=True)
        for img_info in image_list[:50]:
            xref = img_info[0]
            try:
                img_rects = page.get_image_rects(xref)
                for rect in img_rects:
                    bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
                    # 扩大 5pt 边距，覆盖图纸边缘标注
                    figure_regions.append((bbox[0] - 5, bbox[1] - 5, bbox[2] + 5, bbox[3] + 5))
            except Exception:
                pass

        block_idx = 0
        for block in text_dict.get("blocks", []):
            # 图片块 - 跳过，后面统一处理
            if block.get("type") == 1:
                continue

            # 文本块 - 整个 block 合并为一个 TextBlock
            lines = block.get("lines", [])
            if not lines:
                continue

            # 获取整个 block 的 bbox
            block_bbox = block.get("bbox", (0, 0, 0, 0))

            # 合并所有行的文本
            full_text_parts = []
            font_info = {"font": "", "size": 12, "flags": 0, "color": 0}
            has_formula = False
            math_font_spans = 0
            total_spans = 0

            for line in lines:
                line_parts = []
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue

                    total_spans += 1
                    font = span.get("font", "")

                    # 检测数学字体
                    if self.formula_detector.is_math_font(font):
                        math_font_spans += 1
                        has_formula = True
                    elif self.formula_detector.is_formula(text, font):
                        has_formula = True

                    line_parts.append(text)

                    # 记录第一个 span 的字体信息
                    if not font_info["font"]:
                        font_info["font"] = font
                        font_info["size"] = span.get("size", 12)
                        font_info["flags"] = span.get("flags", 0)
                        font_info["color"] = span.get("color", 0)

                if line_parts:
                    full_text_parts.append(" ".join(line_parts))

            if not full_text_parts:
                continue

            # 跳过小字（字号小于阈值的文本块不翻译，通常是注释/标注）
            from config import MIN_FONT_SIZE_TO_TRANSLATE
            if font_info["size"] < MIN_FONT_SIZE_TO_TRANSLATE:
                continue

            full_text = " ".join(full_text_parts)

            # 跳过与图片区域重叠的文本块（图纸中的文字/符号）
            block_bbox_tuple = block_bbox if isinstance(block_bbox, tuple) else tuple(block_bbox)
            if self._is_inside_figure(block_bbox_tuple, figure_regions):
                continue
            formula_span_ranges = []
            search_start = 0
            for line in lines:
                for span in line.get("spans", []):
                    span_text = span.get("text", "").strip()
                    if not span_text:
                        continue
                    font = span.get("font", "")
                    if self.formula_detector.is_math_font(font):
                        idx = full_text.find(span_text, search_start)
                        if idx >= 0:
                            formula_span_ranges.append(FormulaSpan(
                                start=idx,
                                end=idx + len(span_text),
                                text=span_text
                            ))
                            search_start = idx + len(span_text)

            # 过滤太短的文本块（少于3个字符的跳过）
            if len(full_text.strip()) < 3:
                continue

            # 判断块类型
            # 1. 先检查是否为代码块
            is_code = self.code_detector.is_code_block(
                full_text,
                font_info.get("font", ""),
                full_text_parts  # 传递原始行
            )

            # 2. 检查是否为独立公式块
            is_standalone_formula = False

            # 预检查：如果看起来像正常句子，则不是公式
            words = full_text.split()
            avg_word_len = sum(len(w) for w in words) / max(len(words), 1)
            has_long_words = any(len(w) > 10 for w in words)
            has_sentence_pattern = any(p in full_text.lower() for p in [
                ' is the ', ' are the ', ' and the ', ' that the ', ' of the ',
                ' in the ', ' to the ', ' for the ', ' with the ', ' from the ',
                ' can be ', ' will be ', ' has been ', ' have been ',
                ' this ', ' that ', ' which ', ' where ', ' when ',
            ])
            looks_like_sentence = has_sentence_pattern and avg_word_len > 3

            # 只有在不像是句子的情况下才检测公式
            if not looks_like_sentence:
                # 2.1 检查是否大部分 span 使用数学字体
                if total_spans > 0 and math_font_spans / total_spans > 0.4:
                    is_standalone_formula = True

                # 2.2 检查 LaTeX 标记
                if full_text.startswith('$') or full_text.endswith('$'):
                    is_standalone_formula = True

                # 2.3 检查数学符号密度（提高阈值到 0.15）
                formula_ratio = sum(1 for c in full_text if c in self.formula_detector.math_unicode) / max(len(full_text), 1)
                if formula_ratio > 0.15 and not has_long_words:
                    is_standalone_formula = True

                # 2.4 检查纯数学表达式（无字母或只有短变量）
                if not has_long_words and any(c in full_text for c in '=≤≥≠≈'):
                    # 检查是否主要是符号和短变量
                    alpha_chars = sum(1 for c in full_text if c.isalpha())
                    if alpha_chars / max(len(full_text), 1) < 0.5:  # 字母少于50%
                        is_standalone_formula = True

                # 2.5 检查公式编号模式（如 "(1.1)", "(1.2)", "Equation (1)"）
                if re.search(r'\(\d+\.\d+\)\s*$', full_text) or re.search(r'\(\d+\)\s*$', full_text):
                    # 如果包含公式编号，且数学字体比例 > 0.3，或包含等号/不等号且不长
                    if (total_spans > 0 and math_font_spans / total_spans > 0.3) or \
                       (any(c in full_text for c in '=≤≥≠≈') and len(full_text) < 100):
                        is_standalone_formula = True

                # 2.6 检查短公式（包含数学符号且很短且无长词）
                if len(full_text) < 60 and formula_ratio > 0.08 and \
                   not has_long_words and any(c in full_text for c in '=≤≥≠≈+−×÷'):
                    is_standalone_formula = True

            # 3. 检查是否为公式推导段落
            is_derivation = self.formula_detector.is_formula_derivation(full_text)

            # 确定块类型
            if is_code:
                block_type = BlockType.CODE
            elif is_standalone_formula:
                block_type = BlockType.FORMULA
            elif is_derivation:
                block_type = BlockType.FORMULA
            elif font_info["size"] > 16:
                block_type = BlockType.HEADER
            # 特殊处理：References 等标题可能字体不大，需要单独检测
            elif self.section_detector.is_skip_section(full_text):
                block_type = BlockType.REFERENCES
            elif self.section_detector.is_toc_section(full_text):
                block_type = BlockType.HEADER
            else:
                block_type = BlockType.TEXT

            # 决定是否翻译
            # 代码块、公式、图片、参考文献/目录区域内的内容都不翻译

            # 优先检查 References/Appendix 等特殊章节（无论字体大小）
            # 但在目录区域内时，不检测 References/Appendix（避免匹配目录条目）
            # 重要：只有当页面超过总页数的50%时，才触发永久跳过（避免文档开头的误判）
            total_pages = len(self.doc)
            page_progress = page_num / max(total_pages, 1)  # 当前页面进度 (0-1)

            if not self._in_toc_section and self.section_detector.is_skip_section(full_text):
                # 只有在文档后半部分才触发永久跳过
                if page_progress > 0.5:
                    self._in_skip_section = True
                    self._in_toc_section = False
                    print(f"  检测到参考文献/附录区域 (页{page_num+1}/{total_pages}): {full_text[:50]}...")
                    block_type = BlockType.REFERENCES
                    should_translate = False
                else:
                    # 文档前半部分，只标记为REFERENCES但不触发永久跳过
                    print(f"  检测到参考文献关键词但位置靠前，不触发永久跳过 (页{page_num+1}/{total_pages}): {full_text[:50]}...")
                    block_type = BlockType.REFERENCES
                    should_translate = False  # 这个块本身不翻译，但不影响后续页面
            elif block_type == BlockType.HEADER:
                # 检查是否进入目录区域（只有在非参考文献区域时才检测目录）
                if not self._in_skip_section and self.section_detector.is_toc_section(full_text):
                    self._in_toc_section = True
                    print(f"  检测到目录区域: {full_text[:50]}...")
                    should_translate = False
                else:
                    # 遇到新的正常章节标题
                    # 目录区域：遇到非目录章节标题时退出
                    if self._in_toc_section:
                        # 检查是否是新章节（而非目录条目）
                        if self._is_real_chapter_title(full_text, font_info["size"]):
                            print(f"  退出目录区域，检测到新章节: {full_text[:50]}...")
                            self._in_toc_section = False
                    should_translate = True
            elif self._in_skip_section or self._in_toc_section:
                should_translate = False
            else:
                should_translate = block_type in [BlockType.TEXT, BlockType.HEADER]

            text_block = TextBlock(
                id=f"p{page_num}_b{block_idx}",
                block_type=block_type,
                text=full_text,
                original_text=full_text,
                translated_text="",
                bbox=block_bbox,
                page_num=page_num,
                font_info=font_info,
                should_translate=should_translate,
                formula_spans=formula_span_ranges
            )
            blocks.append(text_block)
            block_idx += 1

        # 获取嵌入的图片 - 限制数量避免过多
        image_list = page.get_images(full=True)
        # 只处理前50张图片，避免过多小图标
        for img_idx, img_info in enumerate(image_list[:50]):
            figure_block = self._extract_image(page, img_info, page_num, img_idx)
            if figure_block:
                # 检查图片尺寸，太小的跳过（可能是图标、符号）
                bbox = figure_block.bbox
                width = bbox[2] - bbox[0]
                height = bbox[3] - bbox[1]
                if width > 20 and height > 20:  # 至少20x20像素
                    blocks.append(figure_block)

        # 按位置排序
        blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))

        return PageInfo(
            page_num=page_num,
            width=page.rect.width,
            height=page.rect.height,
            blocks=blocks
        )

    def _create_figure_block(self, block: Dict, page_num: int, idx: int) -> TextBlock:
        return TextBlock(
            id=f"p{page_num}_fig{idx}",
            block_type=BlockType.FIGURE,
            text="[Figure]",
            original_text="",
            translated_text="",
            bbox=tuple(block.get("bbox", (0, 0, 0, 0))),
            page_num=page_num,
            font_info={},
            should_translate=False
        )

    def _extract_image(self, page: fitz.Page, img_info: tuple,
                       page_num: int, idx: int) -> Optional[TextBlock]:
        xref = img_info[0]
        try:
            base_image = self.doc.extract_image(xref)
            image_data = base_image["image"]
            img_rects = page.get_image_rects(xref)
            if img_rects:
                rect = img_rects[0]
                bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
            else:
                bbox = (0, 0, 0, 0)
            return TextBlock(
                id=f"p{page_num}_img{idx}",
                block_type=BlockType.FIGURE,
                text="[Image]",
                original_text="",
                translated_text="",
                bbox=bbox,
                page_num=page_num,
                font_info={},
                should_translate=False,
                image_data=image_data
            )
        except Exception as e:
            print(f"提取图片失败: {e}")
            return None

    def close(self):
        self.doc.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
