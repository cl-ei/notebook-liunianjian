import datetime
from pydantic import BaseModel, Field
from typing import Optional


class FileLike(BaseModel):
    id: Optional[str] = ""
    type: Optional[str] = ""
    text: Optional[str] = ""


class VersionBrief(BaseModel):
    version: int
    base: int
    create_time: datetime.datetime
    lines: int = 0


class IndexFile(BaseModel):
    versions: list[VersionBrief] = Field(default_factory=list)


class DiffItem(BaseModel):
    count: int
    added: bool = False
    removed: bool = False
    value: str = ""


class FileOpenRespData(BaseModel):
    version: int
    base: int
    base_content: str
    diff: list[DiffItem] = Field(default_factory=list)


class VersionFile(BaseModel):
    base: int
    diff: list[DiffItem] = Field(default_factory=list)
    create_time: datetime.datetime


class DiffResp(BaseModel):
    prev_version: int
    prev_content: str
    current_version: int
    current_content: str
