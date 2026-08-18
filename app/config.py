import os
from functools import lru_cache

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class ScannerSettings(BaseModel):
    url: str = "http://localhost:8000/mock/scan"
    timeout: float = 10.0


class DockerSettings(BaseModel):
    repository: str = "owkin-job"
    run_timeout: int = 600
    # parent of the per-job /data volumes; if the service itself runs in a container
    # this exact path has to be bind mounted from the host
    data_dir: str = "/tmp/owkin"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_nested_delimiter="__", extra="ignore")

    server: ServerSettings = ServerSettings()
    scanner: ScannerSettings = ScannerSettings()
    docker: DockerSettings = DockerSettings()
    debug: bool = False

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        # precedence: env > yaml > field defaults. A missing yaml file is fine.
        yaml_file = os.getenv("CONFIG_FILE", "config.yaml")
        return init_settings, env_settings, YamlConfigSettingsSource(settings_cls, yaml_file=yaml_file)


@lru_cache
def get_settings() -> Settings:
    return Settings()
