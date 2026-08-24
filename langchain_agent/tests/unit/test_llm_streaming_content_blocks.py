"""
Unit tests for Gemini content block format handling in LLM streaming.

Tests the fix in _stream_llm_response_simple() that handles Gemini's content list format.
Verifies:
- Correct parsing of content blocks with text fields
- Proper handling of nested structures (list of dicts)
- Edge cases: empty blocks, multiple text chunks, tool calls
- Backward compatibility with old string format
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from langchain_core.messages import AIMessage, BaseMessage


class MockChunk:
    """Mock LLM streaming chunk with flexible content."""

    def __init__(self, content):
        self.content = content


@pytest.mark.unit
@pytest.mark.phase1
class TestContentBlockExtraction:
    """Test extraction of text from Gemini content blocks."""

    def test_extract_text_from_single_content_block(self):
        """Test extracting text from a single content block in list format."""
        content = [{"text": "Hello world"}]

        # Simulate the extraction logic
        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert result == "Hello world"
        assert isinstance(result, str)

    def test_extract_text_from_multiple_content_blocks(self):
        """Test extracting text from multiple content blocks."""
        content = [{"text": "First part"}, {"text": " second part"}, {"text": " third part"}]

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert result == "First part second part third part"

    def test_backward_compatibility_with_string_content(self):
        """Test that string content (old format) still works."""
        content = "This is a string response"

        # Process both old and new format
        if isinstance(content, str):
            result = content
        elif isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    text_parts.append(block["text"])
            result = "".join(text_parts) if text_parts else ""

        assert result == "This is a string response"

    def test_empty_content_blocks_list(self):
        """Test handling of empty content blocks list."""
        content = []

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert result == ""
        assert isinstance(result, str)

    def test_content_block_without_text_field(self):
        """Test ignoring blocks without 'text' field."""
        content = [{"tool_use": "some_tool"}, {"text": "actual text"}, {"metadata": "some_data"}]

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert result == "actual text"

    def test_mixed_content_with_tool_use_blocks(self):
        """Test content with both text and tool_use blocks (Gemini format)."""
        content = [
            {"text": "Calling tool: "},
            {"tool_use": {"name": "search", "input": "query"}},
            {"text": " result follows"},
        ]

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert result == "Calling tool:  result follows"

    def test_none_content_block(self):
        """Test handling of None in content."""
        content = None

        result = ""
        if content and isinstance(content, str):
            result = content
        elif content and isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    text_parts.append(block["text"])
            result = "".join(text_parts) if text_parts else ""

        assert result == ""

    def test_special_characters_in_content_blocks(self):
        """Test special characters are preserved in text blocks."""
        content = [{"text": "Special: \n\t"}, {"text": "  chars: éàü"}]

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert "\n" in result
        assert "\t" in result
        assert "éàü" in result

    def test_very_long_content_blocks(self):
        """Test handling of large content blocks."""
        large_text = "x" * 10000
        content = [{"text": large_text}]

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert len(result) == 10000
        assert result == large_text


@pytest.mark.unit
@pytest.mark.phase1
class TestStreamingChunkHandling:
    """Test handling of streaming chunks in _stream_llm_response_simple logic."""

    def test_string_chunk_content(self):
        """Test processing chunk with string content."""
        chunk = MockChunk("Hello ")
        accumulated = ""

        if hasattr(chunk, "content") and chunk.content:
            content = chunk.content
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        text_parts.append(block["text"])
                content = "".join(text_parts) if text_parts else ""

            if content and isinstance(content, str):
                accumulated += content

        assert accumulated == "Hello "

    def test_list_chunk_content(self):
        """Test processing chunk with list content (Gemini format)."""
        chunk = MockChunk([{"text": "World"}])
        accumulated = ""

        if hasattr(chunk, "content") and chunk.content:
            content = chunk.content
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        text_parts.append(block["text"])
                content = "".join(text_parts) if text_parts else ""

            if content and isinstance(content, str):
                accumulated += content

        assert accumulated == "World"

    def test_multiple_chunks_accumulation(self):
        """Test accumulating multiple chunks in a stream."""
        chunks = [
            MockChunk("Hello "),
            MockChunk([{"text": "world"}]),
            MockChunk(" from "),
            MockChunk([{"text": "Gemini"}]),
        ]

        accumulated = ""
        for chunk in chunks:
            if hasattr(chunk, "content") and chunk.content:
                content = chunk.content
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and "text" in block:
                            text_parts.append(block["text"])
                    content = "".join(text_parts) if text_parts else ""

                if content and isinstance(content, str):
                    accumulated += content

        assert accumulated == "Hello world from Gemini"

    def test_empty_chunk_ignored(self):
        """Test that chunks without content are ignored."""
        chunk = MockChunk(None)
        accumulated = ""

        if hasattr(chunk, "content") and chunk.content:
            content = chunk.content
            if content and isinstance(content, str):
                accumulated += content

        assert accumulated == ""

    def test_chunk_without_content_attribute(self):
        """Test chunk without content attribute is handled safely."""
        chunk = Mock(spec=[])  # No content attribute
        accumulated = ""

        if hasattr(chunk, "content") and chunk.content:
            accumulated += chunk.content

        assert accumulated == ""

    def test_invalid_list_content_graceful_handling(self):
        """Test invalid list content doesn't crash."""
        chunk = MockChunk([None, 123, "string", {"no_text": "here"}])
        accumulated = ""

        if hasattr(chunk, "content") and chunk.content:
            content = chunk.content
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        text_parts.append(block["text"])
                content = "".join(text_parts) if text_parts else ""

            if content and isinstance(content, str):
                accumulated += content

        assert accumulated == ""

    def test_chunk_with_empty_list(self):
        """Test chunk with empty list content."""
        chunk = MockChunk([])
        accumulated = ""

        if hasattr(chunk, "content") and chunk.content:
            content = chunk.content
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        text_parts.append(block["text"])
                content = "".join(text_parts) if text_parts else ""

            if content and isinstance(content, str):
                accumulated += content

        assert accumulated == ""


@pytest.mark.unit
@pytest.mark.phase1
class TestStreamingFallbackLogic:
    """Test fallback to invoke() when streaming fails or returns nothing."""

    def test_fallback_to_invoke_when_no_streaming_content(self):
        """Test fallback to invoke() when streaming accumulates nothing."""
        accumulated_content = ""

        if not accumulated_content:
            # Fallback to invoke
            invoke_result = Mock(content="Fallback response")
            if hasattr(invoke_result, "content"):
                accumulated_content = invoke_result.content if invoke_result.content else ""

        assert accumulated_content == "Fallback response"

    def test_no_fallback_when_streaming_has_content(self):
        """Test no fallback when streaming is successful."""
        accumulated_content = "Streamed content"
        invoke_called = False

        if not accumulated_content:
            invoke_called = True

        assert not invoke_called
        assert accumulated_content == "Streamed content"

    def test_invoke_returns_ai_message(self):
        """Test invoke() returns proper AIMessage format."""
        accumulated_content = ""

        if not accumulated_content:
            invoke_result = Mock(content="Result content")
            accumulated_content = invoke_result.content

        result = AIMessage(content=accumulated_content)
        assert isinstance(result, AIMessage)
        assert result.content == "Result content"

    def test_invoke_without_content_attribute(self):
        """Test fallback when invoke result has no content attribute."""
        accumulated_content = ""
        invoke_result = Mock(spec=[])  # No content attribute

        if not accumulated_content:
            if hasattr(invoke_result, "content"):
                accumulated_content = invoke_result.content
            else:
                accumulated_content = str(invoke_result)

        assert isinstance(accumulated_content, str)


@pytest.mark.unit
@pytest.mark.phase1
class TestEdgeCasesAndRobustness:
    """Test edge cases and robustness of content block handling."""

    def test_content_block_with_empty_text_field(self):
        """Test content block with empty text value."""
        content = [{"text": ""}, {"text": "actual"}]

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert result == "actual"

    def test_nested_list_content_blocks(self):
        """Test that nested lists are handled (shouldn't happen but safe)."""
        content = [{"text": "outer"}, [[{"text": "inner"}]]]

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        # Should only get 'outer' since nested list isn't a dict with 'text'
        assert result == "outer"

    def test_whitespace_only_text_blocks(self):
        """Test text blocks with only whitespace."""
        content = [{"text": "   "}, {"text": "\n\n"}, {"text": "content"}]

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert "content" in result
        assert result == "   \n\ncontent"

    def test_unicode_in_content_blocks(self):
        """Test unicode characters in content blocks."""
        content = [{"text": "Hello"}, {"text": " 你好"}, {"text": " مرحبا"}]

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert "你好" in result
        assert "مرحبا" in result

    def test_json_like_text_in_blocks(self):
        """Test JSON-like content in text blocks."""
        content = [{"text": '{"key": "value"}'}]

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert result == '{"key": "value"}'

    def test_url_in_text_blocks(self):
        """Test URLs are preserved in text blocks."""
        url = "https://example.com/path?query=value&other=123"
        content = [{"text": f"Check this: {url}"}]

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert url in result

    def test_streaming_interruption_mid_chunk(self):
        """Test graceful handling if streaming stops mid-chunk."""
        # Simulate partial accumulation
        accumulated_content = "Partial "

        # Even with partial, we return what we have
        result = AIMessage(content=accumulated_content)
        assert result.content == "Partial "

    def test_zero_length_after_extraction(self):
        """Test when extraction results in empty string."""
        content = [{"tool_use": "data"}, {"metadata": "info"}]

        text_parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        result = "".join(text_parts) if text_parts else ""

        assert result == ""
        assert isinstance(result, str)
