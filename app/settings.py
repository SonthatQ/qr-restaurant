from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # App
    APP_ENV: str = "sandbox"
    APP_BASE_URL: str = "http://192.168.20.74:8000"

    # Auth
    ADMIN_USER: str = "admin"
    ADMIN_PASS: str = "admin123"
    STAFF_USER: str = "staff"
    STAFF_PASS: str = "staff123"

    # DB
    DATABASE_URL: str = "sqlite:///./app.db"

    # SCB
    SCB_MODE: str = "sandbox"  # sandbox|production
    SCB_API_BASE: str = "https://api-sandbox.partners.scb"
    SCB_OAUTH_TOKEN_PATH: str = "/partners/sandbox/v1/oauth/token"

    # IMPORTANT:
    # In some SCB products, the QR create endpoint is not the deeplink endpoint.
    # Keep it configurable; do not hardcode.
    SCB_QR_CREATE_PATH: str = "/partners/sandbox/v3/deeplink/transactions"
    SCB_PAYMENT_INQUIRY_PATH: str = "/partners/sandbox/v1/payment/transactions/{scb_txn_ref}"

    SCB_CLIENT_ID: str = Field(default="", repr=False)
    SCB_CLIENT_SECRET: str = Field(default="", repr=False)

    # Often SCB uses API KEY as ResourceOwnerId header (per SCB Open API examples).
    SCB_API_KEY: str = Field(default="", repr=False)
    SCB_CHANNEL: str = "scbeasy"

    SCB_BILLER_ID: str = ""
    SCB_REF3_PREFIX: str = "SCB"

    SCB_WEBHOOK_SECRET: str = Field(default="", repr=False)
    SCB_WEBHOOK_SIGNATURE_HEADER: str = "x-signature"
    SCB_WEBHOOK_TIMESTAMP_HEADER: str = "x-timestamp"

    SCB_MOCK: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
