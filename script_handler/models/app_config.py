


from typing import Any, Dict, List, Optional, Union
from enum import Enum
from .base_model import BaseModel

class AppType(str,Enum):
    SERVICE = 'service'
    STREAMLIT = 'streamlit'
    PYTHON = 'python'

    UNKNOWN = 'unknown'

    @classmethod
    def _missing_(cls,value):
        return cls.UNKNOWN


class RuntimeConfig(BaseModel):
    entry_file: str
    env: Dict[str,str]
    cli_args: List[Any]

class MetaData(BaseModel):
    imported_from : Optional[str]

class AppConfig(BaseModel):
    app_icon: Optional[str]
    type: AppType
    config: RuntimeConfig


class AppConfigsJson(BaseModel):
    apps: Dict[str,AppConfig] = {}
    metadata: Optional[MetaData]