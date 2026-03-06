"""Tests for HeartbeatService.

We stub out the heavy nanobot.providers package __init__ to avoid pulling in
litellm, oauth_cli_kit, etc. — only nanobot.providers.base is needed.
"""
import asyncio
import os
import sys
import types

import pytest

# ── Prevent nanobot.providers.__init__ from importing heavy providers ──
# We create a stub package that preserves __path__ so sub-module imports work,
# but doesn't import LiteLLMProvider / OpenAICodexProvider.
_nanobot_dir = os.path.join(os.path.dirname(__file__), os.pardir, "nanobot")
_providers_dir = os.path.normpath(os.path.join(_nanobot_dir, "providers"))

if "nanobot.providers" not in sys.modules:
    _pkg = types.ModuleType("nanobot.providers")
    _pkg.__path__ = [_providers_dir]
    _pkg.__package__ = "nanobot.providers"
    _pkg.__file__ = os.path.join(_providers_dir, "__init__.py")
    sys.modules["nanobot.providers"] = _pkg

from nanobot.providers.base import LLMResponse, ToolCallRequest  # noqa: E402
from nanobot.heartbeat.service import HeartbeatService  # noqa: E402


class DummyProvider:
    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def chat(self, *args, **kwargs) -> LLMResponse:
        self.calls.append(kwargs)
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(content="", tool_calls=[])


@pytest.mark.asyncio
async def test_start_is_idempotent(tmp_path) -> None:
    provider = DummyProvider([])

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        interval_s=9999,
        enabled=True,
    )

    await service.start()
    first_task = service._task
    await service.start()

    assert service._task is first_task

    service.stop()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_decide_returns_skip_when_no_tool_call(tmp_path) -> None:
    provider = DummyProvider([LLMResponse(content="no tool call", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    action, tasks = await service._decide("heartbeat content")
    assert action == "skip"
    assert tasks == ""


@pytest.mark.asyncio
async def test_decide_includes_current_time(tmp_path) -> None:
    """Phase 1 should send the current time to the LLM so it can evaluate
    time-based constraints."""
    provider = DummyProvider([LLMResponse(content="skip", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    await service._decide("some content")
    assert len(provider.calls) == 1
    messages = provider.calls[0]["messages"]
    user_msg = messages[-1]["content"]
    assert "Current time:" in user_msg


@pytest.mark.asyncio
async def test_decide_system_prompt_has_time_rules(tmp_path) -> None:
    """The system prompt should instruct the LLM about time-based skip rules."""
    provider = DummyProvider([LLMResponse(content="skip", tool_calls=[])])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    await service._decide("some content")
    system_msg = provider.calls[0]["messages"][0]["content"]
    assert "time range" in system_msg.lower() or "OUTSIDE" in system_msg


@pytest.mark.asyncio
async def test_trigger_now_executes_when_decision_is_run(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text(
        "## Active Tasks\n- [ ] do thing", encoding="utf-8"
    )

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "run", "tasks": "check open tasks"},
                )
            ],
        )
    ])

    called_with: list[str] = []

    async def _on_execute(tasks: str) -> str:
        called_with.append(tasks)
        return "done"

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    result = await service.trigger_now()
    assert result == "done"
    assert len(called_with) == 1
    # The execute prompt should contain the full HEARTBEAT.md content
    assert "HEARTBEAT.md" in called_with[0]
    assert "do thing" in called_with[0]


@pytest.mark.asyncio
async def test_trigger_now_returns_none_when_decision_is_skip(tmp_path) -> None:
    (tmp_path / "HEARTBEAT.md").write_text(
        "## Active Tasks\n- [ ] do thing", encoding="utf-8"
    )

    provider = DummyProvider([
        LLMResponse(
            content="",
            tool_calls=[
                ToolCallRequest(
                    id="hb_1",
                    name="heartbeat",
                    arguments={"action": "skip"},
                )
            ],
        )
    ])

    async def _on_execute(tasks: str) -> str:
        return tasks

    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
        on_execute=_on_execute,
    )

    assert await service.trigger_now() is None


def test_has_active_content_empty() -> None:
    """Empty Active Tasks section should be detected as no active content."""
    content = "# Heartbeat\n## Active Tasks\n<!-- nothing -->\n## Completed\n"
    assert HeartbeatService._has_active_content(content) is False


def test_has_active_content_with_task() -> None:
    """A real task under Active Tasks should be detected."""
    content = "# Heartbeat\n## Active Tasks\n- [ ] check ETF prices\n## Completed\n"
    assert HeartbeatService._has_active_content(content) is True


@pytest.mark.asyncio
async def test_tick_skips_when_no_active_content(tmp_path) -> None:
    """_tick should skip the LLM call entirely when HEARTBEAT.md has no
    active content (only headers and comments)."""
    (tmp_path / "HEARTBEAT.md").write_text(
        "# Heartbeat\n## Active Tasks\n<!-- nothing here -->\n## Completed\n",
        encoding="utf-8",
    )

    provider = DummyProvider([])
    service = HeartbeatService(
        workspace=tmp_path,
        provider=provider,
        model="openai/gpt-4o-mini",
    )

    await service._tick()
    # No LLM call should have been made
    assert len(provider.calls) == 0
