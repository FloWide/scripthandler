
from pydantic import BaseModel as PydanticBaseModel,Field


class BaseModel(PydanticBaseModel):
    class Config:
        arbitrary_types_allowed = True
        underscore_attrs_are_private = True