from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.groq.com/openai/v1"
    deepseek_model: str = "openai/gpt-oss-120b"
    db_path: str = "./agenteqa.db"

    class Config:
        env_file = ".env"
        # .env lo comparten otros modulos (RUNNER_TOKEN/RUNNER_URL los lee runner_client). Con
        # "forbid" el backend no arrancaba, y el error de pydantic imprimia parte del valor al log.
        extra = "ignore"


settings = Settings()
