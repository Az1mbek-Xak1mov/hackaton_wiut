from pydantic import BaseModel


class LlmSettings(BaseModel):
    enabled: bool
    provider: str
    model: str
    configured: bool
    status: str = "ok"          # ok | off | no_key | no_credits | error
    status_text: str = ""


class LlmSettingsUpdate(BaseModel):
    enabled: bool
