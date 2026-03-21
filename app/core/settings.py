from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    sqlite_url: str = "sqlite:///./integra_mvp.db"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    attachment_types: tuple[str, ...] = (
        "invoice",
        "cargo_photo",
        "packing_list",
        "specification",
        "certificate",
        "other",
    )
    attachment_allowed_extensions: tuple[str, ...] = (
        "pdf",
        "jpg",
        "jpeg",
        "png",
        "webp",
        "heic",
        "heif",
        "doc",
        "docx",
        "xls",
        "xlsx",
    )
    attachment_max_files_per_lead: int = 5
    attachment_max_file_size_mb: int = 15

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
