from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://localhost/fourcp"
    admin_api_key: str = "change-me"

    amperon_client_id: str = ""
    amperon_client_secret: str = ""
    nrgstream_username: str = ""
    nrgstream_password: str = ""

    # Microsoft Graph API (Azure AD app with Mail.Send permission)
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""

    # Email addresses
    email_sender: str = ""         # mailbox used to send
    email_primary_to: str = ""     # visible TO line
    email_bcc: str = ""            # comma-separated BCC list
    email_reply_to: str = ""       # optional reply-to

    # Dashboard link settings
    base_url: str = "http://localhost:8000"   # public root
    token_ttl_hours: int = 36                 # how long a view link stays valid


settings = Settings()
