from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.groq.com/openai/v1"
    deepseek_model: str = "openai/gpt-oss-120b"
    db_path: str = "./agenteqa.db"

    class Config:
        env_file = ".env"


settings = Settings()
