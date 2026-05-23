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
    figure_regions: List[tuple] = field(default_factory=list)  # 图片区域 [(x0,y0,x1,y1), ...]


@dataclass
class ChapterInfo:
    """章节信息"""
    title: str
    start_page: int
    end_page: int
    page_count: int


@dataclass
class DocumentSection:
    """文档结构节点"""
    section_type: str    # 'cover','copyright','toc','frontmatter','chapter','chapter_refs','backmatter','index'
    title: str
    start_page: int      # 0-based
    end_page: int        # inclusive, 0-based
    should_translate: bool


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
        """检测是否为需要跳过的章节（参考文献、附录等）

        只匹配独立成段的章节标题，如 "References"、"Index"。
        不匹配正文中的引用，如 "References – Chapter 12"、"For references see..."。
        """
        if not title:
            return False

        title = title.strip()
        # 清理尾部页码和点号
        title_clean = re.sub(r'\s*\d+\s*$', '', title)
        title_clean = re.sub(r'\s*\.\.\..*$', '', title_clean)
        first_line = title_clean.split('\n')[0].strip()

        # 排除章节级参考文献/扩展阅读（如 "References – Chapter 12"、"Further reading  200"）
        # 这些不应触发跳过，只有独立的 "References"、"Index" 才跳过
        text_lower = title_clean.lower()
        chapter_ref_patterns = [
            r'references?\s*[-–—:]\s*(chapter|ch\.?\s*\d|introduction|part)',
            r'further\s+reading\s+\d',  # "Further reading  200" (带页码的目录条目)
        ]
        for p in chapter_ref_patterns:
            if re.search(p, text_lower):
                return False

        # 只匹配完整的标题行（独立成段），不匹配含额外内容的文本
        for pattern in self.patterns_en:
            if pattern.match(title_clean) or pattern.match(first_line):
                return True
        for pattern in self.patterns_zh:
            if pattern.match(title_clean) or pattern.match(first_line):
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

        # 特征2: 章节标题+页码模式（必须在行首，避免匹配正文中的章节引用）
        chapter_pattern = len(re.findall(r'^(Chapter|第\s*\d+\s*章|Section)\s*\d+[^\n]*\s*\d+', text, re.MULTILINE | re.IGNORECASE))
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
        self.document_sections: List[DocumentSection] = []
        self._page_section_map: Dict[int, str] = {}  # page_num -> section_type
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

    @staticmethod
    def _is_reference_entry(text: str) -> bool:
        """检测是否为参考文献条目格式

        匹配模式：
        - [1] Author, Title, Journal, 2012, pp. 100-110.
        - 1. Author, Title, Journal, 2012.
        - AUTHOR, I. 2012. Title. Journal.  (ACM/SIGGRAPH 格式)
        """
        if not text or len(text) < 20:
            return False
        text = text.strip()

        # 模式1：[数字] 开头
        if re.match(r'^\[\d+\]\s', text):
            return True

        # 模式2：数字. 或 数字 空格 开头
        if re.match(r'^\d{1,3}[.\s]\s*[A-Z]', text):
            has_year = bool(re.search(r'\b(19|20)\d{2}\b', text))
            has_authors = bool(re.search(r'[A-Z][a-z]+,\s*[A-Z]', text))
            has_pages = bool(re.search(r'pp\.\s*\d+|pages?\s*\d+', text, re.IGNORECASE))
            has_journal = bool(re.search(r'\b(Journal|Proceedings|Conference|Transactions|Review|Press|Academic|Springer|Wiley|Elsevier|IEEE)\b', text, re.IGNORECASE))
            score = sum([has_year, has_authors, has_pages, has_journal])
            return score >= 2 and ',' in text

        # 模式3：AUTHOR, I. YEAR. 格式（ACM/SIGGRAPH 风格）
        # 特征：大写字母缩写 + 年份 + 句号
        if re.search(r'[A-Z]\.\s*(19|20)\d{2}\.', text) and len(text) > 40:
            return True

        return False

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
        total_pages = len(self.doc)

        # 第零遍：快速扫描文档结构（仅用 get_text，不解析块）
        self._scan_document_structure()
        self._validate_document_structure()

        # 第一遍：解析所有页面，计算平均字体大小
        font_sizes = []
        for page_num in range(total_pages):
            page = self.doc[page_num]
            section_type = self._page_section_map.get(page_num, 'chapter')
            page_info = self._parse_page(page, page_num, section_type)
            self.pages.append(page_info)

            # 收集字体大小
            for block in page_info.blocks:
                if block.font_info.get("size"):
                    font_sizes.append(block.font_info["size"])

        # 计算平均字体大小
        if font_sizes:
            self._avg_font_size = sum(font_sizes) / len(font_sizes)

        # 检测章节边界（基于文档结构）
        self._detect_chapters_from_structure()

        return self.pages

    # ---- 文档结构扫描 ----

    # 大标题检测模式（用于快速扫描，不依赖字体大小）
    _CHAPTER_TITLE_PATTERNS = [
        re.compile(r'^CHAPTER\s+\d+', re.IGNORECASE),
        re.compile(r'^Chapter\s+\d+', re.IGNORECASE),
        re.compile(r'^INTRODUCTION$', re.IGNORECASE),
        re.compile(r'^第[一二三四五六七八九十\d]+[章节篇]'),
    ]

    # 文档末尾区域标题
    _BACK_MATTER_PATTERNS = [
        re.compile(r'^Index$', re.IGNORECASE),
        re.compile(r'^Appendix(es)?$', re.IGNORECASE),
        re.compile(r'^Bibliography$', re.IGNORECASE),
    ]

    def _scan_document_structure(self):
        """快速扫描文档，建立文档结构树

        使用 page.get_text() 快速扫描，不解析块级别。
        建立每页 → section_type 的映射。
        """
        total_pages = len(self.doc)
        if total_pages == 0:
            return

        sections: List[DocumentSection] = []
        page_texts = []

        # 收集每页文本
        for page_num in range(total_pages):
            text = self.doc[page_num].get_text()
            page_texts.append(text)

        # 阶段1：识别关键分界点
        toc_start = None
        toc_end = None
        first_chapter_page = None
        back_matter_start = None  # 文档末尾区域（Index等）的起始页

        for page_num in range(total_pages):
            text = page_texts[page_num]

            # 检测目录页
            if toc_start is None and self.section_detector.is_toc_page(text):
                toc_start = page_num

            # 检测第一个正文章节标题（跳过目录页）
            if first_chapter_page is None and not self.section_detector.is_toc_page(text):
                lines = text.split('\n')
                for line in lines:
                    line_stripped = line.strip()
                    for pat in self._CHAPTER_TITLE_PATTERNS:
                        if pat.match(line_stripped):
                            first_chapter_page = page_num
                            break
                    if first_chapter_page is not None:
                        break
                # 也检测 "Introduction" 等前置章节
                if first_chapter_page is None:
                    for line in lines:
                        s = line.strip()
                        if 3 < len(s) < 60:
                            s_lower = s.lower()
                            if s_lower in ('introduction', 'preface', 'foreword',
                                           'dedication', 'acknowledgments', 'acknowledgements'):
                                first_chapter_page = page_num
                                break

            # 检测文档末尾区域（从后往前找更可靠）
            # 留到后面处理

        # 确定 TOC 结束页
        if toc_start is not None:
            if first_chapter_page is not None and first_chapter_page > toc_start:
                toc_end = first_chapter_page - 1
            else:
                # 目录后找第一页长文本
                for p in range(toc_start + 1, total_pages):
                    if not self.section_detector.is_toc_page(page_texts[p]) and len(page_texts[p]) > 500:
                        toc_end = p - 1
                        break
                if toc_end is None:
                    toc_end = min(toc_start + 10, total_pages - 1)

        # 阶段2：从后往前找文档末尾区域
        # 常见结构：Index 从某页开始到文档末尾
        for page_num in range(total_pages - 1, max(total_pages * 8 // 10, 0), -1):
            text = page_texts[page_num]
            lines = text.split('\n')
            for line in lines:
                line_stripped = line.strip()
                for pat in self._BACK_MATTER_PATTERNS:
                    if pat.match(line_stripped):
                        if back_matter_start is None or page_num < back_matter_start:
                            back_matter_start = page_num
                        break

        # 阶段3：构建结构树
        self.document_sections = []
        self._page_section_map = {}
        sections = self.document_sections  # 直接操作 self.document_sections

        # 3.1 封面/前置区域（TOC 之前的页面）
        cover_end = (toc_start - 1) if toc_start is not None else 0
        if cover_end >= 0:
            # 封面页通常很短或没有文本
            for p in range(0, cover_end + 1):
                self._page_section_map[p] = 'cover'
            sections.append(DocumentSection(
                section_type='cover', title='封面/前置页',
                start_page=0, end_page=cover_end,
                should_translate=False
            ))

        # 3.2 目录区域
        if toc_start is not None and toc_end is not None:
            for p in range(toc_start, toc_end + 1):
                self._page_section_map[p] = 'toc'
            sections.append(DocumentSection(
                section_type='toc', title='目录',
                start_page=toc_start, end_page=toc_end,
                should_translate=False
            ))

        # 3.3 正文区域（TOC 后 → 末尾区域前）
        body_start = (toc_end + 1) if toc_end is not None else (first_chapter_page or 0)
        body_end = (back_matter_start - 1) if back_matter_start is not None else (total_pages - 1)

        if body_start <= body_end:
            # 在正文区域内扫描章节标题和章内 References
            self._scan_body_sections(sections, page_texts, body_start, body_end)

        # 3.4 文档末尾区域
        if back_matter_start is not None:
            for p in range(back_matter_start, total_pages):
                self._page_section_map[p] = 'backmatter'
            sections.append(DocumentSection(
                section_type='backmatter', title='末尾区域(Index/附录)',
                start_page=back_matter_start, end_page=total_pages - 1,
                should_translate=False
            ))

        # 打印结构
        print(f"\n文档结构 ({total_pages} 页):")
        for sec in self.document_sections:
            print(f"  [{sec.start_page+1}-{sec.end_page+1}] {sec.section_type}: {sec.title} "
                  f"(翻译={sec.should_translate})")

    def _scan_body_sections(self, sections: list, page_texts: list,
                            body_start: int, body_end: int):
        """扫描正文区域，识别章节和章内特殊区域

        在正文范围内：
        - 章节标题之间的内容 = 正文 → 翻译
        - 章内 References/Further reading → 不翻译
        """
        total_pages = len(page_texts)

        # 先标记所有正文页为 chapter
        for p in range(body_start, body_end + 1):
            self._page_section_map[p] = 'chapter'
        sections.append(DocumentSection(
            section_type='chapter', title='正文',
            start_page=body_start, end_page=body_end,
            should_translate=True
        ))

        # 在正文中找章内 References/Further reading 页面
        # 这些通常是章节末尾的 "Further reading" 或 "References – Chapter N"
        for p in range(body_start, body_end + 1):
            text = page_texts[p]
            lines = text.split('\n')
            for line in lines:
                line_stripped = line.strip()
                # 章内 References 标题行
                if self._is_chapter_end_section(line_stripped):
                    # 该行所在页标记为 chapter_refs（整页）
                    # 但只有当该行后面跟着的是引用条目时才标记
                    self._page_section_map[p] = 'chapter_refs'
                    break

    @staticmethod
    def _is_chapter_end_section(line: str) -> bool:
        """检测是否为章节末尾的特殊区域标题

        只匹配独立成段的标题行：
        - Further reading
        - References
        - References – Chapter 12

        不匹配：
        - References – Chapter 12 465（目录条目，带页码）
        - Further reading 202（目录条目，带页码）
        """
        if not line or len(line) > 80:
            return False

        # 排除目录条目（带点号+页码 或 空格+页码）
        if re.search(r'\.{2,}\s*\d+$', line):
            return False
        # 排除 "Further reading  202" 这种目录条目
        if re.match(r'^Further\s+reading\s+\d+$', line, re.IGNORECASE):
            return False
        # 排除 "References – Chapter 12 465" 这种目录条目
        if re.match(r'^References?\s*[-–—:]\s*Chapter\s+\d+\s+\d+$', line, re.IGNORECASE):
            return False

        line_lower = line.lower().strip()

        # 匹配 Further reading（独立行）
        if re.match(r'^further\s+reading$', line_lower):
            return True

        # 匹配 References（独立行）
        if re.match(r'^references?$', line_lower):
            return True

        # 匹配 References – Chapter N（章内参考文献）
        if re.match(r'^references?\s*[-–—:]\s*chapter\s+\d+', line_lower):
            return True

        return False

    def _validate_document_structure(self):
        """常识验证文档结构是否合理

        检查规则：
        1. TOC 应在文档前 30%
        2. Index/末尾区域应在文档后 20%
        3. 正文区域应存在且占文档主体
        """
        total_pages = len(self.doc)
        if total_pages == 0 or not self.document_sections:
            return

        has_toc = any(s.section_type == 'toc' for s in self.document_sections)
        has_body = any(s.section_type == 'chapter' for s in self.document_sections)
        has_back = any(s.section_type == 'backmatter' for s in self.document_sections)

        warnings = []
        for sec in self.document_sections:
            mid_page = (sec.start_page + sec.end_page) / 2
            progress = mid_page / max(total_pages, 1)

            if sec.section_type == 'toc' and progress > 0.3:
                warnings.append(f"目录区域出现在文档 {progress:.0%} 处，偏后")
            if sec.section_type == 'backmatter' and progress < 0.7:
                warnings.append(f"末尾区域出现在文档 {progress:.0%} 处，偏前")

        if not has_body:
            warnings.append("未检测到正文区域")

        if warnings:
            print("\n结构常识验证警告:")
            for w in warnings:
                print(f"  ⚠ {w}")
        else:
            print("结构常识验证通过 ✓")

    def _detect_chapters_from_structure(self):
        """基于文档结构和已解析的块信息检测章节"""
        self.chapters = []
        total_pages = len(self.pages)

        # 只在正文区域内检测章节
        body_sections = [s for s in self.document_sections if s.section_type == 'chapter']
        if not body_sections:
            # 没有识别到正文区域，把整个文档作为一个章节
            self.chapters = [ChapterInfo(
                title="全文", start_page=0, end_page=total_pages - 1,
                page_count=total_pages
            )]
            return

        for body_sec in body_sections:
            current_chapter_start = body_sec.start_page
            current_chapter_title = "开始"

            for page_num in range(body_sec.start_page, body_sec.end_page + 1):
                if page_num >= total_pages:
                    break
                page_info = self.pages[page_num]

                # 查找页面上的章节标题
                chapter_title = None
                for block in page_info.blocks:
                    text = block.text.strip()
                    font_size = block.font_info.get("size", 12)

                    if self._is_chapter_heading(text, font_size):
                        chapter_title = text[:50]
                        break

                if chapter_title and page_num > current_chapter_start:
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
            end = min(body_sec.end_page, total_pages - 1)
            if end >= current_chapter_start:
                self.chapters.append(ChapterInfo(
                    title=current_chapter_title,
                    start_page=current_chapter_start,
                    end_page=end,
                    page_count=end - current_chapter_start + 1
                ))

        if not self.chapters and total_pages > 0:
            self.chapters.append(ChapterInfo(
                title="全文", start_page=0, end_page=total_pages - 1,
                page_count=total_pages
            ))

        print(f"\n检测到 {len(self.chapters)} 个章节:")
        for ch in self.chapters:
            print(f"  - {ch.title}: 第{ch.start_page + 1}-{ch.end_page + 1}页 ({ch.page_count}页)")

        # 统计
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

    def _is_chapter_heading(self, text: str, font_size: float) -> bool:
        """判断文本是否为章节标题（用于章节检测）

        关键：即使文本较长，只要开头匹配章节模式且字体够大就算标题。
        因为 PDF 提取时标题可能和正文合并到同一个块。
        """
        if not text:
            return False

        text_stripped = text.strip()

        # 排除目录条目
        if re.search(r'\.{2,}\s*\d+$', text_stripped):
            return False
        if re.match(r'^\d+$', text_stripped):
            return False

        # 字体足够大
        if font_size < self._avg_font_size * 1.2:
            return False

        # 排除章末特殊区域标题（Further reading 等不应成为独立章节）
        first_line = text_stripped.split('\n')[0].strip()
        if self._is_chapter_end_section(first_line):
            return False

        # 匹配章节模式（只看开头，因为标题可能和正文合并在一个块里）
        for pattern in self.CHAPTER_PATTERNS:
            if re.match(pattern, text_stripped, re.IGNORECASE):
                return True

        # 大字体 + 短文本 = 可能是标题（非章节模式的标题）
        if font_size > self._avg_font_size * 1.5 and 3 < len(text_stripped) < 80:
            return True

        return False
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
    def _collect_figure_regions(page: fitz.Page, text_dict: dict) -> list:
        """收集页面上的图片区域（用于跳过图纸中的文字）

        包括：嵌入图片、页面图片、矢量绘图密集区域
        """
        figure_regions = []

        # 从文本字典收集图片块
        for block in text_dict.get("blocks", []):
            if block.get("type") == 1:
                figure_regions.append(block.get("bbox", (0, 0, 0, 0)))

        # 从页面图片收集
        image_list = page.get_images(full=True)
        for img_info in image_list[:50]:
            xref = img_info[0]
            try:
                img_rects = page.get_image_rects(xref)
                for rect in img_rects:
                    bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
                    figure_regions.append((bbox[0] - 5, bbox[1] - 5, bbox[2] + 5, bbox[3] + 5))
            except Exception:
                pass

        # 检测矢量绘图密集区域
        try:
            drawings = page.get_drawings()
            if len(drawings) >= 10:
                path_rects = []
                for drawing in drawings:
                    r = drawing.get("rect")
                    if r and r.width > 2 and r.height > 2:
                        path_rects.append((r.x0, r.y0, r.x1, r.y1))

                if len(path_rects) >= 10:
                    clusters = []
                    used = [False] * len(path_rects)

                    for i in range(len(path_rects)):
                        if used[i]:
                            continue
                        cluster = [path_rects[i]]
                        used[i] = True
                        changed = True
                        while changed:
                            changed = False
                            cx0 = min(r[0] for r in cluster)
                            cy0 = min(r[1] for r in cluster)
                            cx1 = max(r[2] for r in cluster)
                            cy1 = max(r[3] for r in cluster)

                            for j in range(len(path_rects)):
                                if used[j]:
                                    continue
                                rx0, ry0, rx1, ry1 = path_rects[j]
                                rcx = (rx0 + rx1) / 2
                                rcy = (ry0 + ry1) / 2
                                if (cx0 - 80 <= rcx <= cx1 + 80 and
                                        cy0 - 80 <= rcy <= cy1 + 80):
                                    cluster.append(path_rects[j])
                                    used[j] = True
                                    changed = True

                        if len(cluster) >= 8:
                            x0 = min(r[0] for r in cluster)
                            y0 = min(r[1] for r in cluster)
                            x1 = max(r[2] for r in cluster)
                            y1 = max(r[3] for r in cluster)
                            area = (x1 - x0) * (y1 - y0)
                            page_area = page.rect.width * page.rect.height
                            if area > page_area * 0.02:
                                figure_regions.append((x0 - 10, y0 - 10, x1 + 10, y1 + 10))
        except Exception:
            pass

        return figure_regions

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
            # 必须两个方向都有重叠才算有效
            if ox0 < ox1 and oy0 < oy1:
                o_area = (ox1 - ox0) * (oy1 - oy0)
                if o_area / b_area >= overlap_threshold:
                    return True
        return False

    def _parse_page(self, page: fitz.Page, page_num: int,
                    section_type: str = 'chapter') -> PageInfo:
        """解析单页 - 按 block 创建 TextBlock

        Args:
            page: fitz 页面对象
            page_num: 页码（0-based）
            section_type: 文档结构类型（'cover','toc','chapter','chapter_refs','backmatter'）
        """
        blocks = []

        # 封面、目录、末尾区域：跳过整页，不解析块
        if section_type in ('cover', 'toc', 'backmatter'):
            # 对于末尾区域和目录，仍然收集图片信息但不处理文本
            text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            figure_regions = self._collect_figure_regions(page, text_dict)

            # 收集所有文本块，全部标记为不翻译
            block_idx = 0
            for block in text_dict.get("blocks", []):
                if block.get("type") == 1:
                    continue
                lines = block.get("lines", [])
                if not lines:
                    continue
                full_text_parts = []
                font_info = {"font": "", "size": 12, "flags": 0, "color": 0}
                for line in lines:
                    line_parts = [span.get("text", "").strip()
                                  for span in line.get("spans", [])
                                  if span.get("text", "").strip()]
                    if line_parts:
                        full_text_parts.append(" ".join(line_parts))
                    if not font_info["font"] and line.get("spans"):
                        span = line["spans"][0]
                        font_info["font"] = span.get("font", "")
                        font_info["size"] = span.get("size", 12)
                if not full_text_parts:
                    continue
                full_text = " ".join(full_text_parts)
                if len(full_text.strip()) < 3:
                    continue
                text_block = TextBlock(
                    id=f"p{page_num}_b{block_idx}",
                    block_type=BlockType.REFERENCES,
                    text=full_text, original_text=full_text,
                    translated_text="",
                    bbox=block.get("bbox", (0, 0, 0, 0)),
                    page_num=page_num, font_info=font_info,
                    should_translate=False
                )
                blocks.append(text_block)
                block_idx += 1

            return PageInfo(
                page_num=page_num, width=page.rect.width,
                height=page.rect.height, blocks=blocks,
                figure_regions=figure_regions
            )

        # 正文/chapter_refs 页面：正常解析
        page_text = page.get_text()

        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        # 收集图片区域（复用方法）
        figure_regions = self._collect_figure_regions(page, text_dict)

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

            # ============================================================
            # 分类逻辑：由大到小，整体到局部
            # 已在外层根据 section_type 过滤了 cover/toc/backmatter
            # 这里只处理 chapter 和 chapter_refs
            # ============================================================

            total_pages = len(self.doc)
            page_progress = page_num / max(total_pages, 1)

            if section_type == 'chapter_refs':
                # 章内参考文献区域：引用条目不翻译，其他正文翻译
                if self._is_reference_entry(full_text):
                    block_type = BlockType.REFERENCES
                    should_translate = False
                elif self.section_detector.is_skip_section(full_text):
                    block_type = BlockType.REFERENCES
                    should_translate = False
                else:
                    block_type, should_translate = self._classify_paragraph(
                        full_text, font_info, full_text_parts,
                        total_spans, math_font_spans
                    )
            else:
                # 正文页面：正常分类
                # 层次1: 独立成段的参考文献/附录/索引标题
                if self.section_detector.is_skip_section(full_text):
                    block_type = BlockType.REFERENCES
                    should_translate = False

                # 层次2: 文档末尾的引用条目格式
                elif page_progress > 0.85 and self._is_reference_entry(full_text):
                    block_type = BlockType.REFERENCES
                    should_translate = False

                # 层次3: 段落内容分类
                else:
                    block_type, should_translate = self._classify_paragraph(
                        full_text, font_info, full_text_parts,
                        total_spans, math_font_spans
                    )

            # 常识验证
            if not should_translate and block_type != BlockType.TEXT:
                should_translate = self._sanity_check(
                    full_text, block_type, font_info, page_progress
                )
                if should_translate:
                    block_type = BlockType.TEXT

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
            blocks=blocks,
            figure_regions=figure_regions
        )

    def _classify_paragraph(self, full_text: str, font_info: dict,
                            text_lines: list, total_spans: int,
                            math_font_spans: int) -> tuple:
        """层次3: 段落内容分类

        由大到小判断段落类型：
        - 标题 → 翻译
        - 独立公式块 → 不翻译
        - 公式推导段落 → 不翻译
        - 代码块 → 不翻译
        - 正文 → 翻译

        Args:
            full_text: 完整文本
            font_info: 字体信息
            text_lines: 原始行列表
            total_spans: 总 span 数
            math_font_spans: 数学字体 span 数

        Returns:
            (BlockType, should_translate)
        """
        # 3.1 检查是否为标题
        font_size = font_info.get("size", 12)
        if font_size > 16:
            return BlockType.HEADER, True

        # 检查章节标题模式（大字体 + 章节命名模式）
        if font_size > self._avg_font_size * 1.3:
            text_stripped = full_text.strip()
            for pattern in self.CHAPTER_PATTERNS:
                if re.match(pattern, text_stripped, re.IGNORECASE):
                    return BlockType.HEADER, True
            # 短文本 + 大字体也可能是标题
            if len(text_stripped) < 80 and len(text_stripped) > 3:
                return BlockType.HEADER, True

        # 3.2 检查是否为代码块
        is_code = self.code_detector.is_code_block(
            full_text, font_info.get("font", ""), text_lines
        )
        if is_code:
            return BlockType.CODE, False

        # 3.3 检查是否为独立公式块
        is_standalone_formula = self._is_standalone_formula(
            full_text, total_spans, math_font_spans
        )
        if is_standalone_formula:
            return BlockType.FORMULA, False

        # 3.4 检查是否为公式推导段落
        if self.formula_detector.is_formula_derivation(full_text):
            return BlockType.FORMULA, False

        # 3.5 默认为正文，翻译
        return BlockType.TEXT, True

    def _is_standalone_formula(self, full_text: str, total_spans: int,
                               math_font_spans: int) -> bool:
        """检测是否为独立公式块（非行内公式）

        独立公式特征：
        - 整段几乎全是数学内容
        - 不包含正常的英文句子

        Args:
            full_text: 完整文本
            total_spans: 总 span 数
            math_font_spans: 数学字体 span 数

        Returns:
            是否为独立公式块
        """
        if not full_text or len(full_text) < 5:
            return False

        # 预检查：如果包含正常句子模式，大概率不是纯公式
        has_sentence_pattern = any(p in full_text.lower() for p in [
            ' is the ', ' are the ', ' and the ', ' that the ', ' of the ',
            ' in the ', ' to the ', ' for the ', ' with the ', ' from the ',
            ' can be ', ' will be ', ' has been ', ' have been ',
            ' this ', ' that ', ' which ', ' where ', ' when ',
        ])
        words = full_text.split()
        avg_word_len = sum(len(w) for w in words) / max(len(words), 1)
        has_long_words = any(len(w) > 10 for w in words)

        if has_sentence_pattern and avg_word_len > 3:
            return False

        # 数学符号密度
        formula_ratio = sum(
            1 for c in full_text if c in self.formula_detector.math_unicode
        ) / max(len(full_text), 1)

        # 大部分 span 使用数学字体
        if total_spans > 0 and math_font_spans / total_spans > 0.4:
            return True

        # LaTeX 标记
        if full_text.startswith('$') or full_text.endswith('$'):
            return True

        # 数学符号密度高
        if formula_ratio > 0.15 and not has_long_words:
            return True

        # 纯数学表达式（字母少于50%）
        if not has_long_words and any(c in full_text for c in '=≤≥≠≈'):
            alpha_chars = sum(1 for c in full_text if c.isalpha())
            if alpha_chars / max(len(full_text), 1) < 0.5:
                return True

        # 公式编号模式
        has_equation_num = (re.search(r'\(\d+\.\d+\)\s*$', full_text) or
                            re.search(r'\(\d+\)\s*$', full_text))
        if has_equation_num:
            if (total_spans > 0 and math_font_spans / total_spans > 0.3) or \
               (any(c in full_text for c in '=≤≥≠≈') and len(full_text) < 100):
                return True

        # 短公式
        if (len(full_text) < 60 and formula_ratio > 0.08 and
                not has_long_words and any(c in full_text for c in '=≤≥≠≈+−×÷')):
            return True

        return False

    def _sanity_check(self, full_text: str, block_type: BlockType,
                      font_info: dict, page_progress: float) -> bool:
        """常识验证：判断结果不符合常识时，纠正为需要翻译

        检查规则：
        1. 包含正常英文句子的块不应被跳过
        2. 长文本（>200字符）如果是正文风格，不应被跳过
        3. 正常字体大小的正文不应被跳过

        Args:
            full_text: 完整文本
            block_type: 当前判断的块类型
            font_info: 字体信息
            page_progress: 页面进度（0-1）

        Returns:
            True 表示应纠正为翻译，False 表示维持不翻译
        """
        if not full_text:
            return False

        font_size = font_info.get("size", 12)
        text_lower = full_text.lower()
        text_stripped = full_text.strip()

        # 引用条目格式不应被纠正（如 [1] Author, Title... 或 1 Author...）
        if self._is_reference_entry(full_text):
            return False

        # 如果包含明显的正常英文句子结构，很可能是正文
        sentence_signals = [
            ' is the ', ' are the ', ' is a ', ' are a ',
            ' of the ', ' in the ', ' to the ', ' for the ',
            ' with the ', ' from the ', ' by the ',
            ' can be ', ' will be ', ' has been ', ' have been ',
            ' this is ', ' that is ', ' which is ',
            ' it is ', ' there is ', ' there are ',
        ]
        signal_count = sum(1 for s in sentence_signals if s in text_lower)

        # 长文本 + 正常句子结构 = 正文
        if len(full_text) > 200 and signal_count >= 2:
            return True

        # 正常字体大小（接近平均字体）+ 包含句子 = 正文
        if abs(font_size - self._avg_font_size) < 2 and signal_count >= 1:
            return True

        # 包含足够多的英文单词（说明有实际内容）
        words = re.findall(r'[a-zA-Z]{4,}', full_text)
        if len(words) > 10 and len(full_text) > 150:
            return True

        return False

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
