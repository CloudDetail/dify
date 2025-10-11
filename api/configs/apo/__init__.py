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
    APO_DETECT_CLASSIFY_LOWER_Q: float = Field(
        description="apo detect classify lower q",
        default=0.05,
    )
    APO_DETECT_CLASSIFY_UPPER_Q: float = Field(
        description="apo detect classify upper q",
        default=0.95,
    )
    APO_DETECT_CLASSIFY_THRESHOLD: float = Field(
        description="apo detect classify threshold",
        default=2.0,
    )
    APO_DETECT_CLASSIFY_K: float = Field(
        description="apo detect classify k",
        default=3.0,
    )
    APO_DETECT_CLUSTERING_MSE_THRESHOLD: float = Field(
        description="apo detect clustering mse threshold",
        default=0.1,
    )
    APO_DETECT_CLUSTERING_CORR_THRESHOLD: float = Field(
        description="apo detect clustering corr dthreshold",
        default=0.3,
    )
    APO_DETECT_CLUSTERING_DTW_THRESHOLD: float = Field(
        description="apo detect clustering dtw threshold",
        default=0.05,
    )
    APO_DETECT_CLUSTERING_ZSCORE_THRESHOLD: float = Field(
        description="apo detect clustering zscore threshold",
        default=3.0,
    )
    APO_DETECT_SERIES_TREND_MK_ALPHA: float = Field(
        description="apo detect series trend mk alpha",
        default=0.2,
    )
    APO_DETECT_SERIES_TREND_INCREASE_THRESHOLD: float = Field(
        description="apo detect series trend increase threshold",
        default=0.2,
    )
    APO_DETECT_SERIES_TREND_MIN_LENGTH: float = Field(
        description="apo detect series trend min length",
        default=8,
    )
    APO_DETECT_SERIES_SPIKE_WINDOW_SIZE: float = Field(
        description="apo detect series spike window size",
        default=5,
    )
    APO_DETECT_SERIES_SPIKE_MIN_DURATION: float = Field(
        description="apo detect series spike min duration",
        default=1,
    )
    APO_DETECT_SERIES_SPIKE_K_TUKEY: float = Field(
        description="apo detect series spike k tukey",
        default=1,
    )
    APO_DETECT_SERIES_FREQUENCY_WINDOW_SIZE: float = Field(
        description="apo detect series frequency window size",
        default=10,
    )
    APO_DETECT_SERIES_FREQUENCY_AGG_WINDOW_SIZE: float = Field(
        description="apo detect series frequency agg window size",
        default=5,
    )
    APO_DETECT_SERIES_FREQUENCY_THRESHOLD: float = Field(
        description="apo detect series frequency threshold",
        default=3.0,
    )
