from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_version: str = "dev"
    database_url: str = "sqlite+aiosqlite:////config/fetcharr.db"
