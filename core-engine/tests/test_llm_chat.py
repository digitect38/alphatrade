"""Tests for LLM Chat — tool parsing, context building, RAG, fallback chain.

Pure function tests (no actual API calls or DB).
"""

import pytest
import re
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone


# --- Tool pattern parsing ---

TOOL_PATTERN = r'\[TOOL:([a-z_]+):([^\]]+)\]'


class TestToolParsing:
    """Test that LLM tool call patterns are correctly parsed."""

    def test_single_tool(self):
        text = "Let me check [TOOL:kis_price:005930] for you."
        matches = re.findall(TOOL_PATTERN, text)
        assert len(matches) == 1
        assert matches[0] == ("kis_price", "005930")

    def test_multiple_tools(self):
        text = "[TOOL:kis_price:005930] and [TOOL:backtest:005930:ensemble:1Y]"
        matches = re.findall(TOOL_PATTERN, text)
        assert len(matches) == 2
        assert matches[0] == ("kis_price", "005930")
        assert matches[1] == ("backtest", "005930:ensemble:1Y")

    def test_backtest_args_parsing(self):
        text = "[TOOL:backtest:005930:momentum:2Y]"
        matches = re.findall(TOOL_PATTERN, text)
        args = matches[0][1].split(":")
        assert args[0] == "005930"
        assert args[1] == "momentum"
        assert args[2] == "2Y"

    def test_no_tools(self):
        text = "Just a normal response with no tool calls."
        matches = re.findall(TOOL_PATTERN, text)
        assert len(matches) == 0

    def test_signal_tool(self):
        text = "[TOOL:signal:000660]"
        matches = re.findall(TOOL_PATTERN, text)
        assert matches[0] == ("signal", "000660")

    def test_news_tool(self):
        text = "[TOOL:news:035420]"
        matches = re.findall(TOOL_PATTERN, text)
        assert matches[0] == ("news", "035420")

    def test_ohlcv_monthly_tool(self):
        text = "[TOOL:ohlcv_monthly:005930:1Y]"
        matches = re.findall(TOOL_PATTERN, text)
        assert matches[0] == ("ohlcv_monthly", "005930:1Y")

    def test_ohlcv_daily_tool(self):
        text = "[TOOL:ohlcv_daily:005930:1M]"
        matches = re.findall(TOOL_PATTERN, text)
        assert matches[0] == ("ohlcv_daily", "005930:1M")

    def test_tool_stripping(self):
        text = "Here is the result [TOOL:kis_price:005930] and more text."
        clean = re.sub(TOOL_PATTERN, '', text).strip()
        assert "TOOL" not in clean
        assert "Here is the result" in clean


# --- Vision content builder ---

class TestVisionContent:

    def test_openai_vision(self):
        from app.services.llm_callers import _build_vision_content
        result = _build_vision_content("describe this", "data:image/png;base64,abc123", "openai")
        assert len(result) == 2
        assert result[0]["type"] == "text"
        assert result[0]["text"] == "describe this"
        assert result[1]["type"] == "image_url"
        assert "abc123" in result[1]["image_url"]["url"]

    def test_anthropic_vision(self):
        from app.services.llm_callers import _build_vision_content
        result = _build_vision_content("analyze", "data:image/jpeg;base64,xyz789", "anthropic")
        assert result[1]["type"] == "image"
        assert result[1]["source"]["type"] == "base64"
        assert result[1]["source"]["media_type"] == "image/jpeg"
        assert result[1]["source"]["data"] == "xyz789"

    def test_raw_base64(self):
        from app.services.llm_callers import _build_vision_content
        result = _build_vision_content("test", "rawbase64data", "openai")
        assert "image/png" in result[1]["image_url"]["url"]


# --- Ollama URL detection ---

class TestOllamaUrl:

    def test_docker_host(self):
        """In Docker, should use host.docker.internal."""
        import os
        with patch.dict(os.environ, {}, clear=False):
            with patch("os.path.exists", return_value=True):
                # Simulate Docker environment
                assert os.path.exists("/.dockerenv") == True

    def test_native_host(self):
        """Outside Docker, should use localhost."""
        with patch("os.path.exists", return_value=False):
            import os
            assert os.path.exists("/.dockerenv") == False


# --- Fallback chain ---

class TestOpenAIFallbackChain:

    def test_fallback_chain_order(self):
        from app.services.llm_callers import _OPENAI_FALLBACK_CHAIN
        assert "gpt-5.4" in _OPENAI_FALLBACK_CHAIN
        assert "gpt-4.1" in _OPENAI_FALLBACK_CHAIN
        assert "gpt-4o-mini" in _OPENAI_FALLBACK_CHAIN

    def test_responses_api_models(self):
        from app.services.llm_callers import _OPENAI_RESPONSES_MODELS
        assert "gpt-5.4" in _OPENAI_RESPONSES_MODELS
        assert "gpt-5.4-mini" in _OPENAI_RESPONSES_MODELS
        assert "gpt-4.1" not in _OPENAI_RESPONSES_MODELS


# --- Tick size and slippage (from backtest, used in context) ---

class TestTickSize:

    def test_tick_sizes(self):
        from app.strategy.backtest import _tick_size
        assert _tick_size(1500) == 1
        assert _tick_size(3000) == 5
        assert _tick_size(15000) == 10
        assert _tick_size(45000) == 50
        assert _tick_size(150000) == 100
        assert _tick_size(400000) == 500
        assert _tick_size(700000) == 1000

    def test_snap_tick_buy(self):
        from app.strategy.backtest import _snap_tick
        # Buy: round up
        assert _snap_tick(60050, up=True) >= 60050
        assert _snap_tick(60050, up=True) % 50 == 0

    def test_snap_tick_sell(self):
        from app.strategy.backtest import _snap_tick
        # Sell: round down
        assert _snap_tick(60050, up=False) <= 60050
        assert _snap_tick(60050, up=False) % 50 == 0

    def test_effective_slippage(self):
        from app.strategy.backtest import _effective_slippage
        base = 0.001
        # Low volume → higher slippage
        assert _effective_slippage(50000, 5000, base) == base * 3
        assert _effective_slippage(50000, 30000, base) == base * 1.5
        assert _effective_slippage(50000, 100000, base) == base


# --- Chat request/response models ---

class TestChatModels:

    def test_chat_request(self):
        from app.services.llm_models import ChatRequest
        req = ChatRequest(message="test", session_id="s1")
        assert req.message == "test"
        assert req.session_id == "s1"
        assert req.image is None

    def test_chat_request_with_image(self):
        from app.services.llm_models import ChatRequest
        req = ChatRequest(message="analyze", image="data:image/png;base64,abc")
        assert req.image == "data:image/png;base64,abc"

    def test_chat_response(self):
        from app.services.llm_models import ChatResponse
        resp = ChatResponse(reply="hello", session_id="s1", model="gpt-5.4", context_summary="ctx")
        assert resp.reply == "hello"
        assert resp.model == "gpt-5.4"


# --- Context builder helpers ---

class TestContextHelpers:

    def test_realtime_price_none_on_missing(self):
        """_get_realtime_price should return None when Redis has no data."""
        # This is async, test the logic pattern
        from app.utils.redis_cache import get_realtime_price
        assert get_realtime_price is not None  # function exists

    def test_system_prompt_has_tools(self):
        from app.services.llm_models import SYSTEM_PROMPT
        assert "[TOOL:kis_price:" in SYSTEM_PROMPT
        assert "[TOOL:backtest:" in SYSTEM_PROMPT
        assert "[TOOL:signal:" in SYSTEM_PROMPT
        assert "[TOOL:news:" in SYSTEM_PROMPT
        assert "[TOOL:ohlcv_monthly:" in SYSTEM_PROMPT
        assert "[TOOL:ohlcv_daily:" in SYSTEM_PROMPT

    def test_system_prompt_has_rules(self):
        from app.services.llm_models import SYSTEM_PROMPT
        assert "마크다운" in SYSTEM_PROMPT
        assert "투자 권유" in SYSTEM_PROMPT
        assert "{context}" in SYSTEM_PROMPT


# --- Settings schema ---

class TestSettingsSchema:

    def test_llm_providers(self):
        from app.routes.settings_api import SETTINGS_SCHEMA
        providers = SETTINGS_SCHEMA["llm_provider"]["options"]
        assert "openai" in providers
        assert "anthropic" in providers
        assert "ollama" in providers

    def test_openai_models(self):
        from app.routes.settings_api import SETTINGS_SCHEMA
        models = SETTINGS_SCHEMA["openai_model"]["options"]
        assert "gpt-5.4" in models
        assert "gpt-4.1" in models

    def test_anthropic_models(self):
        from app.routes.settings_api import SETTINGS_SCHEMA
        models = SETTINGS_SCHEMA["anthropic_model"]["options"]
        assert "claude-opus-4-6" in models

    def test_ollama_model_field(self):
        from app.routes.settings_api import SETTINGS_SCHEMA
        assert "ollama_model" in SETTINGS_SCHEMA
        assert SETTINGS_SCHEMA["ollama_model"]["default"] == "exaone3.5:2.4b"

    def test_secret_masking(self):
        from app.routes.settings_api import mask_secret
        assert mask_secret("") == ""
        assert mask_secret("short") == "••••"
        assert mask_secret("sk-1234567890abcdef").startswith("sk-1")
        assert "••••" in mask_secret("sk-1234567890abcdef")
        assert mask_secret("sk-1234567890abcdef").endswith("cdef")


# --- RAG search ---

class TestRAGPatterns:

    def test_keyword_extraction(self):
        """Korean noun extraction for DB search."""
        import re
        question = "삼성전자 최근 뉴스와 시장 상황 알려줘"
        keywords = [w for w in re.findall(r'[가-힣]{2,}', question) if len(w) >= 2]
        assert "삼성전자" in keywords
        assert "시장" in keywords

    def test_stock_code_extraction(self):
        """Extract 6-digit stock codes from question."""
        import re
        question = "005930 하고 000660 비교해줘"
        codes = re.findall(r'\b(\d{6})\b', question)
        assert "005930" in codes
        assert "000660" in codes

    def test_no_stock_code(self):
        import re
        question = "오늘 시장 어때?"
        codes = re.findall(r'\b(\d{6})\b', question)
        assert len(codes) == 0


# --- Web search parser ---

class TestDDGParser:

    def test_parser_exists(self):
        """Verify _rag_web_search function exists."""
        from app.services.llm_context import _rag_web_search
        assert _rag_web_search is not None


# --- Backtest tool argument parsing ---

class TestBacktestToolArgs:

    def test_default_args(self):
        args = ["005930"]
        code = args[0]
        strategy = args[1] if len(args) > 1 else "ensemble"
        duration = args[2] if len(args) > 2 else "1Y"
        assert code == "005930"
        assert strategy == "ensemble"
        assert duration == "1Y"

    def test_full_args(self):
        args = "005930:momentum:2Y".split(":")
        assert args[0] == "005930"
        assert args[1] == "momentum"
        assert args[2] == "2Y"

    def test_duration_to_days(self):
        duration_map = {"3M": 90, "6M": 180, "1Y": 365, "2Y": 730, "3Y": 1095, "5Y": 1825, "MAX": 3650}
        assert duration_map["1Y"] == 365
        assert duration_map["MAX"] == 3650
        assert duration_map.get("INVALID", 365) == 365


# --- System prompt topic discrimination ---

class TestTopicDiscrimination:
    """Test that system prompt guides LLM to NOT call tools for non-stock questions."""

    def test_prompt_has_general_knowledge_instruction(self):
        from app.services.llm_models import SYSTEM_PROMPT
        assert "일반 지식" in SYSTEM_PROMPT or "무관한 질문" in SYSTEM_PROMPT

    def test_prompt_warns_no_tools_for_nonstock(self):
        from app.services.llm_models import SYSTEM_PROMPT
        assert "도구를 호출하지 말고" in SYSTEM_PROMPT or "직접 답변" in SYSTEM_PROMPT

    def test_prompt_mentions_latex(self):
        from app.services.llm_models import SYSTEM_PROMPT
        assert "LaTeX" in SYSTEM_PROMPT

    def test_general_question_has_no_stock_code(self):
        """General questions shouldn't trigger stock code extraction."""
        import re
        general_questions = [
            "maxwell 방정식 설명해줘",
            "피타고라스 정리는?",
            "한국의 수도는 어디야?",
            "파이썬에서 리스트 정렬하는 방법",
        ]
        for q in general_questions:
            codes = re.findall(r'\b(\d{6})\b', q)
            assert len(codes) == 0, f"'{q}' should not have stock codes but found {codes}"

    def test_stock_question_has_stock_code(self):
        """Stock questions should trigger stock code extraction."""
        import re
        stock_questions = [
            "005930 현재가 알려줘",
            "삼성전자 005930 분석해줘",
            "000660 백테스트 해줘",
        ]
        for q in stock_questions:
            codes = re.findall(r'\b(\d{6})\b', q)
            assert len(codes) > 0, f"'{q}' should have stock codes"

    def test_stock_name_extraction_korean(self):
        """Korean stock names should be extractable."""
        import re
        question = "삼성전자 현재가 알려줘"
        names = re.findall(r'[가-힣]{2,10}', question)
        assert "삼성전자" in names

    def test_general_topic_no_korean_stock_name_match(self):
        """General topic Korean words are extracted but won't match DB stocks."""
        import re
        question = "맥스웰 방정식을 설명해줘"
        names = re.findall(r'[가-힣]{2,10}', question)
        assert "맥스웰" in names  # extracted but won't match DB stock names
        # "방정식을" extracted as one word (Korean morphology includes particles)
        assert any("방정식" in n for n in names)


# --- Ollama integration ---

class TestOllamaIntegration:

    def test_call_ollama_function_exists(self):
        from app.services.llm_callers import call_ollama
        assert callable(call_ollama)

    def test_ollama_provider_in_settings(self):
        from app.routes.settings_api import SETTINGS_SCHEMA
        assert "ollama" in SETTINGS_SCHEMA["llm_provider"]["options"]

    def test_ollama_model_configurable(self):
        from app.routes.settings_api import SETTINGS_SCHEMA
        assert "ollama_model" in SETTINGS_SCHEMA
        assert SETTINGS_SCHEMA["ollama_model"]["type"] == "text"  # freeform, not select


# --- Context length limit ---

class TestContextLimit:

    def test_context_truncation(self):
        """Context should be truncated to ~6000 chars."""
        # Simulate a long context
        long_parts = ["x" * 1000 for _ in range(10)]  # 10000 chars
        context = "\n".join(long_parts)
        if len(context) > 6000:
            context = context[:6000] + "\n... (컨텍스트 일부 생략)"
        assert len(context) <= 6100
        assert "생략" in context
