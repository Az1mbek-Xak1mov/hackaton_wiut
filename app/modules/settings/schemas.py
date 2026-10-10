from pydantic import BaseModel


class LlmSettings(BaseModel):
    enabled: bool
    provider: str
    model: str
    configured: bool


class LlmSettingsUpdate(BaseModel):
    enabled: bool
