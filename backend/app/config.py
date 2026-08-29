from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    db_path: str = "./agenteqa.db"

    class Config:
        env_file = ".env"


settings = Settings()
