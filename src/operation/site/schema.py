from typing import Any
from pydantic import BaseModel, Field, ConfigDict, field_validator


SITE_CONFIG_FILE = "_site_config.yaml"


class Site(BaseModel):
    model_config = ConfigDict(extra="ignore")  # 宽松模式：忽略未知字段

    name: str = Field("流年笺", description="站点名称")
    url: str = Field(default="", description="生产环境根域名")
    path_prefix: str = Field(default="", description="Web访问前缀，类似Jekyll的baseurl")
    lang: str = Field(default="zh-CN")
    timezone: str = Field(default="Asia/Shanghai")


class BuildConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")  # 宽松模式：忽略未知字段

    source_root: str = ""
    statics_dir: str = ""
    permalink: str = "/posts/:slug/"
    default_layout: str = "post"
    base_path: str = ""

    @field_validator('default_layout')
    @classmethod
    def vali_default_layout(cls, v: str) -> str:
        for c in ("/", " ", ":", "\\", ".."):
            if c in v:
                raise ValueError(f"default_layout must not contains char: {c}")
        return v


class FeaturesConfig(BaseModel):
    """功能开关配置"""
    model_config = ConfigDict(extra="ignore")

    toc: bool = Field(default=True, description="全局目录开关")
    lazy_load: bool = Field(default=True, description="全局懒加载模式开关")

class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")  # 宽松模式：忽略未知字段

    site: Site
    build: BuildConfig
    features: FeaturesConfig


# -------- 渲染管线的产物 --------
class ImageRef(BaseModel):
    """不可变的图片引用记录"""
    raw: str
    src: str
    alt: str
    title: str | None = Field(default=None)


class TocItem(BaseModel):
    level: int
    text: str      # 纯文本（已转义）
    anchor: str    # URL 安全的锚点


# -------- 文章解析 --------
class Article(BaseModel):
    """文章数据类，承载从MD到HTML的所有中间状态"""
    index: int = Field(default=0)   # 索引，用于生成上一页、下一页
    src_path: str                   # 源文件路径 (e.g., /_posts/example.md)
    dest_url: str                   # 目标URL (e.g., /posts/cortex-m33-nvic-config/)
    fm: dict[str, Any]              # fm: Front Matter
    raw_content: str                # 原始MD内容（不含FM）
    rendered_html: str = ""         # 渲染后的HTML
    toc: list[TocItem] = Field(default_factory=list)
    images: list[ImageRef] = Field(default_factory=list)
    code_css: str                   # code 渲染出来的 css
