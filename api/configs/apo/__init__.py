from pydantic import Field
from pydantic_settings import BaseSettings


class APOConfig(BaseSettings):
    """
    Configuration settings for apo
    """

    APO_BACKEND_URL: str = Field(
        description="apo backend url",
        default="http://localhost:8080",
    )
    APO_VM_URL: str = Field(
        description="apo vm url",
        default="http://localhost:8080",
    )
    INITIAL_LANGUAGE: str = Field(
        description="Initial workflows' language",
        default="en-US"
    )
    WORKFLOW_DIR: str = Field(
        description="Directory of workflows yaml file.",
        default="./init_data/workflows"
    )
    OFFLINE_MODE: bool = Field(
        description="Offline mode",
        default=False
    )
    DATAPLANE_URL: str = Field(
        description="dataplane url",
        default="http://localhost:8089"
    )
    APO_KNOWLEDGE_BASE_URL: str = Field(
        description="apo knowledge base url",
        default="http://localhost:8080",
    )
    APO_KNOWLEDGE_BASE_API_KEY: str = Field(
        description="apo knowledge base api key",
        default="",
    )
    APO_DEFAULT_KNOWLEDGE_BASE_ID: str = Field(
        description="apo knowledge base default id",
        default="syncause_default",
    )
