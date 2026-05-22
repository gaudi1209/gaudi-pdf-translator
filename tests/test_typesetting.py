import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pdf_rebuilder import TypesettingHelper


def test_line_start_no_cjk_punctuation():
    helper = TypesettingHelper()
    assert helper.is_forbidden_at_line_start("，")
    assert helper.is_forbidden_at_line_start("。")
    assert helper.is_forbidden_at_line_start("！")
    assert helper.is_forbidden_at_line_start("？")
    assert helper.is_forbidden_at_line_start("）")
    assert helper.is_forbidden_at_line_start("】")
    assert helper.is_forbidden_at_line_start("》")
    assert not helper.is_forbidden_at_line_start("我")
    assert not helper.is_forbidden_at_line_start("A")


def test_line_end_no_cjk_punctuation():
    helper = TypesettingHelper()
    assert helper.is_forbidden_at_line_end("（")
    assert helper.is_forbidden_at_line_end("【")
    assert helper.is_forbidden_at_line_end("《")
    assert not helper.is_forbidden_at_line_end("。")


def test_cjk_latin_spacing():
    helper = TypesettingHelper()
    assert helper.needs_cjk_latin_space("中A") is True
    assert helper.needs_cjk_latin_space("A中") is True
    assert helper.needs_cjk_latin_space("中文") is False
    assert helper.needs_cjk_latin_space("AB") is False


def test_calculate_scale_basic():
    helper = TypesettingHelper()
    scale = helper.calculate_optimal_scale(
        text="这是测试",
        box_width=200,
        box_height=50,
        original_size=12
    )
    assert scale == 1.0


def test_calculate_scale_shrink():
    helper = TypesettingHelper()
    scale = helper.calculate_optimal_scale(
        text="这是一段非常非常非常长的测试文本需要缩小字体才能放下" * 5,
        box_width=200,
        box_height=50,
        original_size=12
    )
    assert scale < 1.0
    assert scale >= 0.5


def test_font_mapping_serif():
    helper = TypesettingHelper()
    result = helper.map_to_chinese_font("TimesNewRoman")
    assert result["style"] == "serif"


def test_font_mapping_sans():
    helper = TypesettingHelper()
    result = helper.map_to_chinese_font("Arial")
    assert result["style"] == "sans"


def test_font_mapping_bold():
    helper = TypesettingHelper()
    result = helper.map_to_chinese_font("Arial-Bold")
    assert result["bold"] is True


def test_font_fallback_chain():
    helper = TypesettingHelper()
    result = helper.map_to_chinese_font("UnknownFont123")
    assert result["path"] is not None
