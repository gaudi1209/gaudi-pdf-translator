"""
OpenAI 兼容 API 翻译服务
支持 OpenAI / DeepSeek / Ollama (OpenAI兼容模式) / 任意兼容端点
"""
import requests
import time
from typing import Optional
from dataclasses import dataclass


@dataclass
class TranslationResult:
    original: str
    translated: str
    success: bool
    source_lang: str = ""
    error: Optional[str] = None


class OpenAITranslateService:
    """OpenAI 兼容翻译服务"""

    def __init__(self,
                 model: str = "gpt-4o-mini",
                 base_url: str = "https://api.openai.com/v1",
                 api_key: str = "",
                 max_retries: int = 3,
                 timeout: int = 120):
        self.model = model
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.max_retries = max_retries
        self.timeout = timeout

    def _build_messages(self, text: str) -> list:
        return [
            {"role": "system", "content":
                "You are a professional translator. Translate the following text to Chinese. "
                "Only output the translation, no explanations. "
                "Preserve any placeholders like {v1}, {v2}, ___FORMULA_0___ exactly as they are."},
            {"role": "user", "content": text}
        ]

    def translate(self, text: str, source_lang: str = None) -> TranslationResult:
        if not text or not text.strip():
            return TranslationResult(original=text, translated=text, success=True)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        payload = {
            "model": self.model,
            "messages": self._build_messages(text),
            "temperature": 0.3
        }

        for attempt in range(self.max_retries):
            try:
                resp = requests.post(url, json=payload, headers=headers,
                                     timeout=self.timeout)
                if resp.status_code == 200:
                    translated = resp.json()["choices"][0]["message"]["content"].strip()
                    if translated.startswith('"') and translated.endswith('"'):
                        translated = translated[1:-1]
                    return TranslationResult(
                        original=text, translated=translated, success=True,
                        source_lang=source_lang or ""
                    )
                else:
                    raise Exception(f"API {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return TranslationResult(
                        original=text, translated=text, success=False, error=str(e),
                        source_lang=source_lang or ""
                    )

        return TranslationResult(original=text, translated=text, success=False,
                                 source_lang=source_lang or "", error="Max retries exceeded")
