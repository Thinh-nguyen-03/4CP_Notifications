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

    # When true, Amperon and NRGStream HTTP calls are skipped; synthetic data is used instead.
    use_mock_fetchers: bool = False
    # Which slot label to attach to mock Amperon data: 3AM or 11AM
    mock_fetch_slot: str = "11AM"

    # Microsoft Graph API (Azure AD app with Mail.Send permission)
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""

    # Email addresses
    email_sender: str = ""         # mailbox used to send  e.g. pnguyen@poweredbysenergy.com
    email_primary_to: str = ""     # visible TO line       e.g. EnergyManagement@poweredbysenergy.com
    email_bcc: str = ""            # comma-separated BCC list (the actual client recipients)
    email_reply_to: str = ""       # optional reply-to (leave blank to use email_sender)

    # Dashboard link settings
    base_url: str = "http://localhost:8000"   # public root, e.g. https://fourcp.onrender.com
    token_ttl_hours: int = 36                 # how long a view link stays valid


settings = Settings()
