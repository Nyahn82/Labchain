from pathlib import Path

from pydantic import SecretStr
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

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent.parent / ".env",
        env_file_encoding="utf-8",
        hide_input_in_errors=True,
    )


settings = Settings()
