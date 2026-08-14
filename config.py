import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

_REQUIRED_VARS = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REFRESH_TOKEN",
    "GEMINI_API_KEY",
    "NOTION_TOKEN",
    "NOTION_PEOPLE_DATA_SOURCE_ID",
    "NOTION_ORGANIZATIONS_DATA_SOURCE_ID",
    "NOTION_AFFILIATIONS_DATA_SOURCE_ID",
    "NOTION_EMAIL_ADDRESSES_DATA_SOURCE_ID",
    "NOTION_EMAIL_DIGESTS_DATA_SOURCE_ID",
    "DB_PATH",
    "LOG_PATH",
]


class ConfigError(Exception):
    pass


@dataclass
class Config:
    google_client_id: str
    google_client_secret: str
    google_refresh_token: str
    gemini_api_key: str
    notion_token: str
    notion_people_data_source_id: str
    notion_organizations_data_source_id: str
    notion_affiliations_data_source_id: str
    notion_email_addresses_data_source_id: str
    notion_email_digests_data_source_id: str
    db_path: str
    log_path: str


def load_config() -> Config:
    missing = [name for name in _REQUIRED_VARS if not os.environ.get(name)]
    if missing:
        raise ConfigError(
            f"Missing required environment variable(s): {', '.join(missing)}. "
            f"Copy env.example to .env and fill in real values."
        )
    return Config(
        google_client_id=os.environ["GOOGLE_CLIENT_ID"],
        google_client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        google_refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        gemini_api_key=os.environ["GEMINI_API_KEY"],
        notion_token=os.environ["NOTION_TOKEN"],
        notion_people_data_source_id=os.environ["NOTION_PEOPLE_DATA_SOURCE_ID"],
        notion_organizations_data_source_id=os.environ["NOTION_ORGANIZATIONS_DATA_SOURCE_ID"],
        notion_affiliations_data_source_id=os.environ["NOTION_AFFILIATIONS_DATA_SOURCE_ID"],
        notion_email_addresses_data_source_id=os.environ["NOTION_EMAIL_ADDRESSES_DATA_SOURCE_ID"],
        notion_email_digests_data_source_id=os.environ["NOTION_EMAIL_DIGESTS_DATA_SOURCE_ID"],
        db_path=os.environ["DB_PATH"],
        log_path=os.environ["LOG_PATH"],
    )
