"""
翻译服务模块
支持 Ollama 本地模型翻译
自动检测源语言（英语、德语等）
"""
import time
import sys
import os
import requests
import re
from typing import List, Optional, Callable
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.formula_detector import FormulaProtector


@dataclass
class TranslationResult:
    """翻译结果"""
    original: str
    translated: str
    success: bool
    source_lang: str = ""
    error: Optional[str] = None


class LanguageDetector:
    """简单的语言检测器"""

    # 常见德语词汇和特征
    GERMAN_PATTERNS = [
        r'\b(der|die|das|und|ist|ein|eine|auf|für|mit|von|zu|den|dem|des|nicht|als|auch|wird|werden|hat|haben|sind|oder|aber|bei|durch|nach|über|unter|vor|wenn|dann|diese|dieser|dieses|welche|welcher|welches|alle|wieder|gegen|ohne|um|bis|seit|noch|nur|wie|war|waren|wurde|wurden|kann|können|muss|müssen|soll|sollen|wollen|möchte|möchten)\b',
        r'\b(sch|ch|ß|ä|ö|ü|Ä|Ö|Ü)\b',  # 德语特有字符
        r'\b(ung|heit|keit|schaft|tum|nis|sal|ling|ig|lich|isch|bar|sam|haft|los|arm|reich|voll)\b',  # 德语后缀
    ]

    # 常见英语词汇
    ENGLISH_PATTERNS = [
        r'\b(the|and|is|are|was|were|been|being|have|has|had|do|does|did|will|would|could|should|may|might|must|shall|can|need|dare|ought|used|to|of|in|for|on|with|at|by|from|as|into|through|during|before|after|above|below|between|under|again|further|then|once|here|there|when|where|why|how|all|each|few|more|most|other|some|such|no|nor|not|only|own|same|so|than|too|very|just|over|also|back|even|still|way|well|only|new|because|any|these|those|this|that|which|who|whom|what|whose)\b',
    ]

    @classmethod
    def detect(cls, text: str) -> str:
        """检测文本语言，返回语言代码"""
        if not text or not text.strip():
            return "en"

        text_lower = text.lower()

        # 计算德语特征得分
        german_score = 0
        for pattern in cls.GERMAN_PATTERNS:
            matches = len(re.findall(pattern, text_lower, re.IGNORECASE))
            german_score += matches

        # 计算英语特征得分
        english_score = 0
        for pattern in cls.ENGLISH_PATTERNS:
            matches = len(re.findall(pattern, text_lower, re.IGNORECASE))
            english_score += matches

        # 根据得分判断语言
        if german_score > english_score * 0.8:  # 德语特征足够明显
            return "de"
        else:
            return "en"


class OllamaTranslateService:
    """Ollama 本地翻译服务"""

    def __init__(self, model='translategemma:27b', ollama_url='http://localhost:11434'):
        self.model = model
        self.ollama_url = ollama_url
        self.max_retries = 3
        self.retry_delay = 1.0

    def translate(self, text: str, source_lang: str = None) -> TranslationResult:
        """翻译单段文本"""
        if not text or not text.strip():
            return TranslationResult(original=text, translated=text, success=True)

        # 自动检测语言（仅用于日志）
        if source_lang is None:
            source_lang = LanguageDetector.detect(text)

        # 统一使用英语提示词（更稳定，translategemma 模型能自动识别源语言）
        prompt = f'Translate the following text to Chinese. Only output the translation, no explanations:\n\n{text}'

        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    f'{self.ollama_url}/api/generate',
                    json={
                        'model': self.model,
                        'prompt': prompt,
                        'stream': False
                    },
                    timeout=120
                )

                if response.status_code == 200:
                    result = response.json()
                    translated = result.get('response', '').strip()
                    # 清理可能的引号包裹
                    if translated.startswith('"') and translated.endswith('"'):
                        translated = translated[1:-1]
                    return TranslationResult(
                        original=text,
                        translated=translated,
                        success=True,
                        source_lang=source_lang
                    )
                else:
                    raise Exception(f'Ollama API error: {response.status_code}')

            except Exception as e:
                error_msg = str(e)
                print(f"翻译失败 (尝试 {attempt + 1}/{self.max_retries}): {error_msg}")

                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    return TranslationResult(
                        original=text,
                        translated=text,
                        success=False,
                        source_lang=source_lang,
                        error=error_msg
                    )

        return TranslationResult(original=text, translated=text, success=False,
                                 source_lang=source_lang, error="Max retries exceeded")

    def translate_batch(self, texts: List[str],
                        callback: Optional[Callable] = None) -> List[TranslationResult]:
        """批量翻译"""
        results = []
        total = len(texts)

        for i, text in enumerate(texts):
            result = self.translate(text)
            results.append(result)

            if callback:
                callback(i + 1, total, result)

        return results


class ProtectedTranslator:
    """带公式保护的翻译器（使用 Ollama，自动检测语言）"""

    def __init__(self, model='translategemma:27b', cache_dir: str = None):
        self.translate_service = OllamaTranslateService(model=model)
        self.formula_protector = FormulaProtector()
        self.model = model
        self._cache = None
        if cache_dir:
            from services.translation_cache import TranslationCache
            self._cache = TranslationCache(cache_dir)

    def _normalize_spaces(self, text: str) -> str:
        """规范化空格，只在列表项前保留换行"""
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

    def translate_with_protection(self, text: str) -> TranslationResult:
        """翻译并保护公式，自动检测源语言"""
        if not text or not text.strip():
            return TranslationResult(original=text, translated=text, success=True)

        # 缓存查询
        if self._cache:
            cached = self._cache.get(text, self.model)
            if cached is not None:
                return TranslationResult(original=text, translated=cached, success=True)

        # 1. 检测并保护公式
        protected_text, formulas = self.formula_protector.protect(text)

        # 2. 翻译保护后的文本（自动检测语言）
        result = self.translate_service.translate(protected_text)

        if result.success:
            # 3. 恢复公式
            result.translated = self.formula_protector.restore(
                result.translated, formulas
            )
            # 4. 规范化空格
            result.translated = self._normalize_spaces(result.translated)

            # 5. 写入缓存
            if self._cache:
                self._cache.put(text, result.translated, self.model)

        return result


# 单例翻译器
_translator_instance = None


def get_translator() -> ProtectedTranslator:
    """获取翻译器单例"""
    global _translator_instance
    if _translator_instance is None:
        _translator_instance = ProtectedTranslator()
    return _translator_instance


def translate_text(text: str) -> TranslationResult:
    """便捷翻译函数"""
    return get_translator().translate_with_protection(text)
