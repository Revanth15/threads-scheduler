from pydantic_settings import BaseSettings
from typing import Optional
import pytz

class Settings(BaseSettings):
    # Threads API
    THREADS_APP_ID: str = ""
    THREADS_APP_SECRET: str = ""
    THREADS_ACCESS_TOKEN: str = ""
    THREADS_USER_ID: str = ""

    # OpenRouter AI
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "deepseek/deepseek-v4-pro"

    # Scheduler — 5 daily posting slots (set hour to -1 to disable a slot)
    TIMEZONE: str = "Asia/Singapore"

    # Slot 1: Early morning commute
    SLOT_1_HOUR: int = 7
    SLOT_1_MINUTE: int = 30
    SLOT_1_TYPE: str = "morning_commute"

    # Slot 2: Late morning / mid-day
    SLOT_2_HOUR: int = 10
    SLOT_2_MINUTE: int = 0
    SLOT_2_TYPE: str = "midday"

    # Slot 3: Lunch break
    SLOT_3_HOUR: int = 12
    SLOT_3_MINUTE: int = 30
    SLOT_3_TYPE: str = "lunch"

    # Slot 4: Evening commute
    SLOT_4_HOUR: int = 17
    SLOT_4_MINUTE: int = 30
    SLOT_4_TYPE: str = "evening_commute"

    # Slot 5: Night wind-down
    SLOT_5_HOUR: int = 21
    SLOT_5_MINUTE: int = 0
    SLOT_5_TYPE: str = "night"

    # Minimum posts per day (3-5)
    MIN_POSTS_PER_DAY: int = 3
    MAX_POSTS_PER_DAY: int = 5

    # Legacy support
    MORNING_POST_HOUR: int = 8
    MORNING_POST_MINUTE: int = 0
    EVENING_POST_HOUR: int = 18
    EVENING_POST_MINUTE: int = 0

    # Content
    CONTENT_FILE: str = "content.md"
    MAX_POST_LENGTH: int = 500

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./threads_scheduler.db"

    # App
    SECRET_KEY: str = "change-me-in-production"
    DEBUG: bool = False
    PORT: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    def get_active_slots(self) -> list[dict]:
        """Return all enabled posting slots sorted by hour."""
        slots = []
        for i in range(1, 6):
            hour = getattr(self, f"SLOT_{i}_HOUR")
            if hour >= 0:
                slots.append({
                    "slot": i,
                    "hour": hour,
                    "minute": getattr(self, f"SLOT_{i}_MINUTE"),
                    "type": getattr(self, f"SLOT_{i}_TYPE"),
                })
        return sorted(slots, key=lambda s: (s["hour"], s["minute"]))

settings = Settings()
