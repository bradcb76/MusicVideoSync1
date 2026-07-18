from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class QueueRequest(BaseModel):
    track_id: int = Field(gt=0)
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    dry_run: bool = True


class SchedulerStartRequest(BaseModel):
    dry_run: bool = True


class SettingsRequest(BaseModel):
    daily_limit: int = Field(default=250, ge=1, le=5000)
    retry_delay_seconds: float = Field(default=5, ge=0, le=3600)


class SearchRequest(BaseModel):
    artist: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
