"""
公式检测模块 - 增强的公式识别和保护策略
用于翻译时保护公式不被翻译
"""
import re
from typing import List, Tuple
from dataclasses import dataclass


@dataclass
class FormulaRegion:
    """公式区域"""
    start: int      # 在文本中的起始位置
    end: int        # 结束位置
    formula: str    # 公式内容
    is_latex: bool  # 是否是 LaTeX


class FormulaProtector:
    """公式保护器 - 在翻译时保护公式"""

    def __init__(self):
        # LaTeX 命令模式
        self.latex_commands = [
            # 希腊字母
            r'\\(alpha|beta|gamma|delta|epsilon|zeta|eta|theta|iota|kappa|'
            r'lambda|mu|nu|xi|pi|rho|sigma|tau|upsilon|phi|chi|psi|omega)',
            # 运算符
            r'\\(frac|sqrt|sum|prod|int|oint|partial|nabla|infty)',
            # 关系符
            r'\\(le|ge|ne|approx|equiv|sim|propto|pm|mp)',
            # 结构
            r'\\(left|right|begin|end|over|binom)',
            # 符号
            r'\\(cdot|times|div|langle|rangle)',
        ]

        # Unicode 数学符号
        self.math_unicode = {
            # 积分类
            '∑', '∏', '∫', '∬', '∮', '∯', '∰',
            # 根号
            '√', '∛', '∜',
            # 微积分
            '∞', '∂', '∇',
            # 希腊小写
            'α', 'β', 'γ', 'δ', 'ε', 'ζ', 'η', 'θ', 'ι', 'κ', 'λ', 'μ',
            'ν', 'ξ', 'π', 'ρ', 'σ', 'τ', 'υ', 'φ', 'χ', 'ψ', 'ω',
            # 希腊大写
            'Α', 'Β', 'Γ', 'Δ', 'Ε', 'Ζ', 'Η', 'Θ', 'Ι', 'Κ', 'Λ', 'Μ',
            'Ν', 'Ξ', 'Ο', 'Π', 'Ρ', 'Σ', 'Τ', 'Υ', 'Φ', 'Χ', 'Ψ', 'Ω',
            # 集合
            '∈', '∉', '⊂', '⊃', '⊆', '⊇', '∪', '∩', '∅',
            # 逻辑
            '∀', '∃', '∄',
            # 运算
            '±', '∓', '×', '÷', '≠', '≈', '≡', '≤', '≥',
            # 箭头
            '→', '←', '↔', '⇒', '⇐', '⇔', '↑', '↓',
        }

        # 数学表达式正则
        self.math_expr_patterns = [
            r'\$[^$]+\$',                    # $...$ 行内公式
            r'\$\$[^$]+\$\$',                # $$...$$ 行间公式
            r'\\[[\s\S]+?\\]',              # \[...\] LaTeX 环境
            r'\\([^)]+\\)',                  # \(...\) LaTeX 行内
            r'[a-zA-Z]\^\{[^}]+\}',          # 指数 x^{...}
            r'[a-zA-Z]_\{[^}]+\}',           # 下标 x_{...}
            r'[a-zA-Z]\^\d+',                # 指数 x^2
            r'[a-zA-Z]_\d+',                 # 下标 x_2
            r'\\frac\{[^}]+\}\{[^}]+\}',     # 分数 \frac{a}{b}
        ]

    def detect_formulas(self, text: str) -> List[FormulaRegion]:
        """检测文本中的所有公式区域"""
        regions = []

        # 方法1：检测 LaTeX 模式
        for pattern in self.math_expr_patterns:
            for match in re.finditer(pattern, text):
                regions.append(FormulaRegion(
                    start=match.start(),
                    end=match.end(),
                    formula=match.group(),
                    is_latex=True
                ))

        # 方法2：检测 Unicode 数学符号密集区域
        regions.extend(self._detect_unicode_math_regions(text))

        # 方法3：检测 LaTeX 命令
        regions.extend(self._detect_latex_commands(text))

        # 合并重叠区域
        regions = self._merge_regions(regions)

        return regions

    def _detect_unicode_math_regions(self, text: str) -> List[FormulaRegion]:
        """检测 Unicode 数学符号密集区域"""
        regions = []

        # 找到所有数学符号的位置
        math_positions = []
        for i, char in enumerate(text):
            if char in self.math_unicode:
                math_positions.append(i)

        if not math_positions:
            return regions

        # 聚类相邻的符号
        clusters = []
        current_cluster = [math_positions[0]]

        for pos in math_positions[1:]:
            if pos - current_cluster[-1] <= 5:  # 相邻5个字符内
                current_cluster.append(pos)
            else:
                clusters.append(current_cluster)
                current_cluster = [pos]
        clusters.append(current_cluster)

        # 将密集区域标记为公式
        for cluster in clusters:
            if len(cluster) >= 2:  # 至少2个数学符号
                start = max(0, cluster[0] - 2)
                end = min(len(text), cluster[-1] + 3)

                # 扩展到完整词边界
                while start > 0 and text[start - 1].isalnum():
                    start -= 1
                while end < len(text) and text[end].isalnum():
                    end += 1

                regions.append(FormulaRegion(
                    start=start,
                    end=end,
                    formula=text[start:end],
                    is_latex=False
                ))

        return regions

    def _detect_latex_commands(self, text: str) -> List[FormulaRegion]:
        """检测 LaTeX 命令"""
        regions = []

        combined_pattern = '|'.join(self.latex_commands)
        for match in re.finditer(combined_pattern, text, re.IGNORECASE):
            # 扩展到完整表达式
            start, end = self._extend_latex_expr(text, match.start(), match.end())
            regions.append(FormulaRegion(
                start=start,
                end=end,
                formula=text[start:end],
                is_latex=True
            ))

        return regions

    def _extend_latex_expr(self, text: str, start: int, end: int) -> Tuple[int, int]:
        """扩展 LaTeX 表达式边界"""
        # 向左扩展
        while start > 0:
            if text[start - 1] in ' \t\n':
                break
            if text[start - 1] in '{}[]()':
                start -= 1
                continue
            if text[start - 1].isalnum() or text[start - 1] in '\\_^{}':
                start -= 1
            else:
                break

        # 向右扩展
        while end < len(text):
            if text[end] in ' \t\n':
                break
            if text[end] in '{}[]()':
                end += 1
                continue
            if text[end].isalnum() or text[end] in '\\_^{}+-=<>':
                end += 1
            else:
                break

        return start, end

    def _merge_regions(self, regions: List[FormulaRegion]) -> List[FormulaRegion]:
        """合并重叠的区域"""
        if not regions:
            return []

        # 按起始位置排序
        regions.sort(key=lambda r: r.start)

        merged = [regions[0]]
        for region in regions[1:]:
            last = merged[-1]
            if region.start <= last.end:
                # 合并
                merged[-1] = FormulaRegion(
                    start=last.start,
                    end=max(last.end, region.end),
                    formula=text[last.start:max(last.end, region.end)] if 'text' in dir() else last.formula,
                    is_latex=last.is_latex or region.is_latex
                )
            else:
                merged.append(region)

        return merged

    def protect(self, text: str) -> Tuple[str, List[Tuple[str, str]]]:
        """
        保护公式，返回替换后的文本和公式列表
        返回: (protected_text, [(placeholder, formula), ...])
        """
        regions = self.detect_formulas(text)

        formulas = []
        protected_text = text

        # 从后向前替换，避免位置偏移
        for i, region in enumerate(reversed(regions)):
            placeholder = f"___FORMULA_{len(regions) - 1 - i}___"
            protected_text = (
                protected_text[:region.start] +
                placeholder +
                protected_text[region.end:]
            )
            formulas.append((placeholder, region.formula))

        return protected_text, formulas

    def restore(self, text: str, formulas: List[Tuple[str, str]]) -> str:
        """恢复公式"""
        result = text
        for placeholder, formula in formulas:
            result = result.replace(placeholder, formula)
        return result


# 便捷函数
def protect_formulas(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """保护文本中的公式"""
    protector = FormulaProtector()
    return protector.protect(text)


def restore_formulas(text: str, formulas: List[Tuple[str, str]]) -> str:
    """恢复文本中的公式"""
    protector = FormulaProtector()
    return protector.restore(text, formulas)


class InlineFormulaProtector:
    """行内公式保护器 - 用占位符替换公式区域"""

    def __init__(self):
        pass

    def protect_spans(self, text: str, formula_ranges: list) -> tuple:
        """将指定范围替换为占位符

        Args:
            text: 完整文本
            formula_ranges: [(start, end), ...] 公式位置列表

        Returns:
            (protected_text, placeholders) 其中 placeholders = [(placeholder, original), ...]
        """
        if not formula_ranges:
            return text, []

        # 按位置排序，从后向前替换
        sorted_ranges = sorted(formula_ranges, key=lambda r: r[0], reverse=True)
        placeholders = []
        protected = text

        for i, (start, end) in enumerate(sorted_ranges):
            placeholder = f"___F{i}___"
            original = text[start:end]
            placeholders.append((placeholder, original))
            protected = protected[:start] + placeholder + protected[end:]

        # 顺序反转为正序
        placeholders.reverse()
        return protected, placeholders

    def restore(self, text: str, placeholders: list) -> str:
        """恢复占位符为原始公式"""
        result = text
        for placeholder, original in placeholders:
            result = result.replace(placeholder, original)
        return result
