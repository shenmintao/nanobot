"""Scene awareness — time, holiday, weather, and context-aware conversation hints."""

from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import Any

from loguru import logger

from nanobot.sillytavern.types import SceneContext


# ============================================================================
# Lunar Calendar Holidays (dynamic via lunardate)
# ============================================================================

def _lunar_to_solar(year: int, lunar_month: int, lunar_day: int) -> date | None:
    """Convert a lunar date to solar (Gregorian) date.

    Uses the `lunardate` library for accurate conversion.
    Falls back gracefully if the library is not installed.
    """
    try:
        from lunardate import LunarDate
        ld = LunarDate(year, lunar_month, lunar_day)
        return ld.toSolarDate()
    except ImportError:
        logger.debug("lunardate not installed, lunar holidays unavailable. Install with: pip install lunardate")
        return None
    except Exception:
        return None


def _get_lunar_holidays(year: int) -> dict[str, str]:
    """Dynamically compute lunar holiday dates for the given year.

    Returns a dict of MM-DD (solar) -> holiday name.
    """
    # Lunar holidays: (lunar_month, lunar_day, name)
    lunar_holidays = [
        (1, 1, "春节"),
        (1, 15, "元宵节"),
        (5, 5, "端午节"),
        (7, 7, "七夕"),
        (7, 15, "中元节"),
        (8, 15, "中秋节"),
        (9, 9, "重阳节"),
        (12, 30, "除夕"),  # May not exist in some years (29-day month)
    ]

    result: dict[str, str] = {}
    for lm, ld, name in lunar_holidays:
        solar = _lunar_to_solar(year, lm, ld)
        if solar:
            result[solar.strftime("%m-%d")] = name

    # Try 除夕 fallback: if 12/30 doesn't exist, try 12/29
    if not any(v == "除夕" for v in result.values()):
        solar = _lunar_to_solar(year, 12, 29)
        if solar:
            result[solar.strftime("%m-%d")] = "除夕"

    return result


def _get_solar_holidays() -> dict[str, str]:
    """Return fixed solar (Gregorian) holidays. MM-DD -> name."""
    return {
        "01-01": "元旦",
        "02-14": "情人节",
        "03-08": "妇女节",
        "03-12": "植树节",
        "04-01": "愚人节",
        "05-01": "劳动节",
        "05-04": "青年节",
        "06-01": "儿童节",
        "09-10": "教师节",
        "10-01": "国庆节",
        "10-31": "万圣节",
        "11-11": "双十一/光棍节",
        "12-24": "平安夜",
        "12-25": "圣诞节",
    }


def _get_variable_solar_holidays(year: int) -> dict[str, str]:
    """Compute variable-date solar holidays (e.g. Mother's Day = 2nd Sunday of May)."""
    result: dict[str, str] = {}

    # 清明节: April 4 or 5 (simplified: use April 5 for most years)
    result["04-05"] = "清明节"

    # Mother's Day: 2nd Sunday of May
    may1 = date(year, 5, 1)
    first_sunday = may1 + timedelta(days=(6 - may1.weekday()) % 7)
    mothers_day = first_sunday + timedelta(weeks=1)
    result[mothers_day.strftime("%m-%d")] = "母亲节"

    # Father's Day: 3rd Sunday of June
    jun1 = date(year, 6, 1)
    first_sunday = jun1 + timedelta(days=(6 - jun1.weekday()) % 7)
    fathers_day = first_sunday + timedelta(weeks=2)
    result[fathers_day.strftime("%m-%d")] = "父亲节"

    # Thanksgiving: 4th Thursday of November (US)
    nov1 = date(year, 11, 1)
    first_thursday = nov1 + timedelta(days=(3 - nov1.weekday()) % 7)
    thanksgiving = first_thursday + timedelta(weeks=3)
    result[thanksgiving.strftime("%m-%d")] = "感恩节"

    return result


def _get_all_holidays(year: int) -> dict[str, str]:
    """Get all holidays for the given year (solar + lunar + variable)."""
    holidays = _get_solar_holidays()
    holidays.update(_get_variable_solar_holidays(year))
    holidays.update(_get_lunar_holidays(year))  # Lunar overrides solar if same date
    return holidays


# ============================================================================
# Time Period Classification
# ============================================================================

_TIME_PERIODS = [
    (0, 5, "凌晨", "夜深了，注意休息"),
    (5, 8, "早晨", "新的一天开始了"),
    (8, 11, "上午", None),
    (11, 13, "中午", "该吃午饭了"),
    (13, 17, "下午", None),
    (17, 19, "傍晚", "快下班了"),
    (19, 22, "晚上", None),
    (22, 24, "深夜", "夜深了，早点休息"),
]

_DAY_NAMES_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def _classify_time_period(hour: int) -> tuple[str, str | None]:
    """Return (period_name, optional_hint) for the given hour."""
    for start, end, name, hint in _TIME_PERIODS:
        if start <= hour < end:
            return name, hint
    return "深夜", "夜深了，早点休息"


# ============================================================================
# Scene Awareness Engine
# ============================================================================

class SceneAwareness:
    """Builds scene context for conversation-aware responses.

    Collects time, holiday, weather, emotion, and interaction data
    to create a SceneContext that can be injected into the system prompt.
    """

    def __init__(self, timezone: str | None = None):
        self._timezone = timezone
        # Track first-chat date per session for "days since" calculation
        self._first_chat_dates: dict[str, str] = {}
        # Track today's chat count per session
        self._chat_counts: dict[str, tuple[str, int]] = {}  # session_key -> (date_str, count)
        # Cache holidays per year to avoid recomputation
        self._holiday_cache: dict[int, dict[str, str]] = {}

    def _now(self) -> datetime:
        """Get current datetime, optionally in user's timezone."""
        if self._timezone:
            try:
                from zoneinfo import ZoneInfo
                return datetime.now(ZoneInfo(self._timezone))
            except Exception:
                pass
        return datetime.now()

    def _get_holidays(self, year: int) -> dict[str, str]:
        """Get holidays for a year, with caching."""
        if year not in self._holiday_cache:
            self._holiday_cache[year] = _get_all_holidays(year)
        return self._holiday_cache[year]

    def record_chat(self, session_key: str) -> None:
        """Record a chat interaction for counting purposes."""
        now = self._now()
        date_str = now.strftime("%Y-%m-%d")

        # Track first chat date
        if session_key not in self._first_chat_dates:
            self._first_chat_dates[session_key] = date_str

        # Track today's count
        prev_date, prev_count = self._chat_counts.get(session_key, ("", 0))
        if prev_date == date_str:
            self._chat_counts[session_key] = (date_str, prev_count + 1)
        else:
            self._chat_counts[session_key] = (date_str, 1)

    def build_context(
        self,
        session_key: str = "",
        user_emotion: str = "",
        user_emotion_intensity: int = 50,
    ) -> SceneContext:
        """Build the current scene context."""
        now = self._now()
        hour = now.hour
        weekday = now.weekday()  # 0=Monday

        time_period, _ = _classify_time_period(hour)
        day_type = "周末" if weekday >= 5 else "工作日"
        day_name = _DAY_NAMES_ZH[weekday]

        # Holiday check
        holidays = self._get_holidays(now.year)
        date_key = now.strftime("%m-%d")
        holiday = holidays.get(date_key, "")

        # Chat count
        date_str = now.strftime("%Y-%m-%d")
        _, chat_count = self._chat_counts.get(session_key, (date_str, 0))

        # Days since first chat
        first_date_str = self._first_chat_dates.get(session_key, date_str)
        try:
            first_date = datetime.strptime(first_date_str, "%Y-%m-%d")
            days_since = (now.replace(tzinfo=None) - first_date).days
        except (ValueError, TypeError):
            days_since = 0

        # Anniversary notes
        anniversary_note = self._check_anniversary(days_since)

        return SceneContext(
            time_period=time_period,
            day_type=day_type,
            day_of_week=day_name,
            holiday=holiday,
            weather="",  # Weather integration is optional, can be added later
            user_emotion=user_emotion,
            user_emotion_intensity=user_emotion_intensity,
            today_chat_count=chat_count,
            last_chat_time=now.strftime("%H:%M"),
            days_since_first_chat=days_since,
            anniversary_note=anniversary_note,
        )

    @staticmethod
    def _check_anniversary(days: int) -> str:
        """Check if today is a notable anniversary."""
        milestones = {
            1: "今天是我们认识的第1天！",
            7: "我们认识一周了！",
            30: "我们认识一个月了！",
            50: "我们认识50天了！",
            100: "我们认识100天了！🎉",
            200: "我们认识200天了！",
            365: "我们认识一周年了！🎂",
            500: "我们认识500天了！",
            730: "我们认识两周年了！🎂",
            1000: "我们认识1000天了！🎉",
        }
        return milestones.get(days, "")

    def format_scene_prompt(
        self,
        session_key: str = "",
        user_emotion: str = "",
        user_emotion_intensity: int = 50,
    ) -> str:
        """Format scene context as a prompt section for injection."""
        ctx = self.build_context(session_key, user_emotion, user_emotion_intensity)
        lines: list[str] = []

        # Time info
        lines.append(f"当前时间段: {ctx.time_period} ({ctx.day_of_week}, {ctx.day_type})")

        # Holiday
        if ctx.holiday:
            lines.append(f"🎉 今天是{ctx.holiday}！")

        # Weather (if available)
        if ctx.weather:
            lines.append(f"天气: {ctx.weather}")

        # Interaction stats
        if ctx.today_chat_count > 0:
            lines.append(f"今天已聊天{ctx.today_chat_count}次")

        if ctx.days_since_first_chat > 0:
            lines.append(f"认识天数: 第{ctx.days_since_first_chat}天")

        # Anniversary
        if ctx.anniversary_note:
            lines.append(ctx.anniversary_note)

        # Behavior hints based on time
        _, hint = _classify_time_period(self._now().hour)
        if hint:
            lines.append(f"💡 {hint}")

        if not lines:
            return ""

        return "## 当前场景\n" + "\n".join(lines) + "\n\n请根据以上场景自然地调整你的语气和话题。"
