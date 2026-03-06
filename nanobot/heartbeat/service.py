"""Heartbeat service - periodic agent wake-up to check for tasks."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider

_HEARTBEAT_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "heartbeat",
            "description": "Report heartbeat decision after reviewing tasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["skip", "run"],
                        "description": (
                            "skip = no active tasks right now (e.g. all completed, "
                            "outside scheduled hours, or only comments/headers remain). "
                            "run = there are concrete, actionable tasks that should be "
                            "executed RIGHT NOW given the current time."
                        ),
                    },
                    "tasks": {
                        "type": "string",
                        "description": (
                            "When action=run, provide the FULL original task descriptions "
                            "from HEARTBEAT.md (copy them verbatim, do NOT summarize). "
                            "Include all details such as specific items to check, "
                            "time constraints, delivery instructions, etc."
                        ),
                    },
                },
                "required": ["action"],
            },
        },
    }
]

_DECIDE_SYSTEM_PROMPT = """\
You are a heartbeat scheduler. Your ONLY job is to decide whether the tasks \
in HEARTBEAT.md should be executed RIGHT NOW.

Rules for deciding:
1. If there are NO tasks under "## Active Tasks" (only headers, comments, or \
blank lines), choose "skip".
2. If a task specifies a time range (e.g. "9:00-17:00" or "weekdays only") \
and the current time is OUTSIDE that range, choose "skip".
3. If a task says "stop", "pause", "disabled", or is checked off [x], \
choose "skip" for that task.
4. Only choose "run" if there are concrete, unchecked tasks that should be \
executed at the current time.
5. When choosing "run", copy the task descriptions VERBATIM from the file — \
do NOT summarize or shorten them.

Call the heartbeat tool with your decision."""


class HeartbeatService:
    """
    Periodic heartbeat service that wakes the agent to check for tasks.

    Phase 1 (decision): reads HEARTBEAT.md and asks the LLM — via a virtual
    tool call — whether there are active tasks at the current time.  The LLM
    receives the current timestamp so it can respect time-based constraints
    (e.g. "only during market hours").

    Phase 2 (execution): only triggered when Phase 1 returns ``run``.  The
    ``on_execute`` callback runs the task through the full agent loop with
    the original HEARTBEAT.md content so the agent has full context.
    """

    def __init__(
        self,
        workspace: Path,
        provider: LLMProvider,
        model: str,
        on_execute: Callable[[str], Coroutine[Any, Any, str]] | None = None,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        interval_s: int = 30 * 60,
        enabled: bool = True,
    ):
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.on_execute = on_execute
        self.on_notify = on_notify
        self.interval_s = interval_s
        self.enabled = enabled
        self._running = False
        self._task: asyncio.Task | None = None

    @property
    def heartbeat_file(self) -> Path:
        return self.workspace / "HEARTBEAT.md"

    def _read_heartbeat_file(self) -> str | None:
        if self.heartbeat_file.exists():
            try:
                return self.heartbeat_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    async def _decide(self, content: str) -> tuple[str, str]:
        """Phase 1: ask LLM to decide skip/run via virtual tool call.

        Returns (action, tasks) where action is 'skip' or 'run'.
        The LLM receives the current time so it can evaluate time-based
        constraints in the task definitions.
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        response = await self.provider.chat(
            messages=[
                {"role": "system", "content": _DECIDE_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"Current time: {now}\n\n"
                    "Review the following HEARTBEAT.md and decide whether there "
                    "are active tasks to execute right now.\n\n"
                    f"```markdown\n{content}\n```"
                )},
            ],
            tools=_HEARTBEAT_TOOL,
            model=self.model,
        )

        if not response.has_tool_calls:
            return "skip", ""

        args = response.tool_calls[0].arguments
        return args.get("action", "skip"), args.get("tasks", "")

    async def start(self) -> None:
        """Start the heartbeat service."""
        if not self.enabled:
            logger.info("Heartbeat disabled")
            return
        if self._running:
            logger.warning("Heartbeat already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Heartbeat started (every {}s)", self.interval_s)

    def stop(self) -> None:
        """Stop the heartbeat service."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run_loop(self) -> None:
        """Main heartbeat loop."""
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Heartbeat error: {}", e)

    async def _tick(self) -> None:
        """Execute a single heartbeat tick."""
        content = self._read_heartbeat_file()
        if not content:
            logger.debug("Heartbeat: HEARTBEAT.md missing or empty")
            return

        # Quick check: if there's nothing under Active Tasks, skip the LLM call
        if not self._has_active_content(content):
            logger.debug("Heartbeat: no active content in HEARTBEAT.md")
            return

        logger.info("Heartbeat: checking for tasks...")

        try:
            action, tasks = await self._decide(content)

            if action != "run":
                logger.info("Heartbeat: OK (nothing to report)")
                return

            logger.info("Heartbeat: tasks found, executing...")
            if self.on_execute:
                # Pass the full HEARTBEAT.md content + LLM-extracted tasks
                # so the agent has complete context for execution
                execute_prompt = (
                    "[Heartbeat Task] The following tasks from HEARTBEAT.md need to be executed now.\n\n"
                    f"## Tasks\n{tasks}\n\n"
                    f"## Full HEARTBEAT.md\n```\n{content}\n```\n\n"
                    "Execute these tasks. Use available tools (web search, shell, etc.) as needed. "
                    "Provide concrete results with real data."
                )
                response = await self.on_execute(execute_prompt)
                if response and self.on_notify:
                    logger.info("Heartbeat: completed, delivering response")
                    await self.on_notify(response)
        except Exception:
            logger.exception("Heartbeat execution failed")

    @staticmethod
    def _has_active_content(content: str) -> bool:
        """Quick heuristic: check if HEARTBEAT.md has non-comment, non-header
        content under Active Tasks.  This avoids an LLM call when the file
        is clearly empty."""
        in_active = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("## active"):
                in_active = True
                continue
            if in_active:
                if stripped.startswith("## "):
                    break  # hit next section
                if stripped and not stripped.startswith("<!--") and not stripped.startswith("#"):
                    return True
        return False

    async def trigger_now(self) -> str | None:
        """Manually trigger a heartbeat."""
        content = self._read_heartbeat_file()
        if not content:
            return None
        action, tasks = await self._decide(content)
        if action != "run" or not self.on_execute:
            return None
        execute_prompt = (
            "[Heartbeat Task] The following tasks from HEARTBEAT.md need to be executed now.\n\n"
            f"## Tasks\n{tasks}\n\n"
            f"## Full HEARTBEAT.md\n```\n{content}\n```\n\n"
            "Execute these tasks. Use available tools (web search, shell, etc.) as needed. "
            "Provide concrete results with real data."
        )
        return await self.on_execute(execute_prompt)
