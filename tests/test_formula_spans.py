import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.formula_detector import InlineFormulaProtector


def test_protect_empty():
    protector = InlineFormulaProtector()
    text, ph = protector.protect_spans("hello world", [])
    assert text == "hello world"
    assert ph == []


def test_protect_single():
    protector = InlineFormulaProtector()
    text, ph = protector.protect_spans("hello X+Y world", [(6, 9)])
    assert "___F0___" in text
    assert ph[0][1] == "X+Y"


def test_protect_multiple():
    protector = InlineFormulaProtector()
    text, ph = protector.protect_spans("a x+y b c=d e", [(2, 5), (8, 11)])
    assert "___F0___" in text
    assert "___F1___" in text


def test_restore_roundtrip():
    protector = InlineFormulaProtector()
    original = "The value of x + y and a = b are equal."
    protected, ph = protector.protect_spans(original, [(14, 19), (24, 29)])
    restored = protector.restore(protected, ph)
    assert restored == original
