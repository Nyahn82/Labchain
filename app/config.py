from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "RHU LabChain"
    environment: str = "production"

    node_id: str
    node_name: str
    node_port: int = 5001

    db_host: str
    db_port: int = 3306
    db_name: str
    db_user: str
    db_password: SecretStr

    auth_session_ttl_minutes: int = Field(default=480, ge=1, le=525600)
    auth_session_cookie_name: str = Field(default="rhu_session", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    auth_csrf_cookie_name: str = Field(default="rhu_csrf", pattern=r"^[A-Za-z0-9_-]{1,64}$")
    auth_cookie_secure: bool = True
    auth_cookie_samesite: Literal["strict", "lax"] = "strict"

    @model_validator(mode="after")
    def validate_auth_cookies(self):
        if self.auth_session_cookie_name == self.auth_csrf_cookie_name:
            raise ValueError("Authentication cookie names must differ.")
        if self.environment.lower() == "production" and not self.auth_cookie_secure:
            raise ValueError("Production authentication requires Secure cookies and HTTPS.")
        return self

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        hide_input_in_errors=True,
    )


settings = Settings()
