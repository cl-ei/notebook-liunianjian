import logging
import os.path
import re
import yaml
import datetime
from xpinyin import Pinyin
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
from src.framework.error import ErrorWithPrompt
from src.operation.site.schema import SiteConfig, Article, SITE_CONFIG_FILE
from src.operation.site.rendering import MarkdownRenderPipeline


DATE_FORMAT = "%Y-%m-%d"

# 针对 slug 提取的规则
_INVISIBLE_RE = re.compile(r'[\s\0-\1f\7f\u200b\u200c\u200d\ufeff]')  # 覆盖空白/控制字符/零宽字符/BOM
_NON_ALLOWED_RE = re.compile(r'[^0-9a-zA-Z/_.-]')                     # 仅保留允许的字符
_MULTI_DASH_RE = re.compile(r'-+')                                    # 匹配连续中划线


def normalize_identifier(s: str) -> str:
    """
    规范化字符串，专为SSG的slug、文件名、URL路径生成设计：
    1. 将所有不可见字符（含空格、换行、零宽字符等）替换为中划线`-`
    2. 仅保留数字、大小写字母，以及 `-` `/` `_` `.` 四类符号
    3. 合并连续的中划线为单个
    4. 去除首尾的中划线

    参数:
        s: 原始输入字符串（如文章标题、分类名等）
    返回:
        规范化后的字符串，全为非法字符时返回空串
    """
    # 1. 不可见字符统一转为中划线
    s = _INVISIBLE_RE.sub('-', s)
    # 2. 过滤非允许字符
    s = _NON_ALLOWED_RE.sub('', s)
    # 3. 合并连续中划线
    s = _MULTI_DASH_RE.sub('-', s)
    # 4. 剔除首尾中划线
    return s.strip('-')


class ArticleBuilder:
    """构建Article对象"""

    def __init__(self, config: SiteConfig, storage_root: str):
        self.config = config
        self.storage_root = storage_root

    @staticmethod
    def parse_front_matter(content: str, fm_delimiter: str = "---") -> tuple[dict, str]:
        """解析文件头和正文"""
        if not content.startswith(fm_delimiter):
            # 没有FM，视为普通页面
            return {}, content

        try:
            _, fm_raw, body = content.split(fm_delimiter, 2)
        except ValueError:
            # 格式错误，兜底处理
            return {}, content

        try:
            fm = yaml.safe_load(fm_raw) or {}
        except yaml.YAMLError as e:
            raise ErrorWithPrompt(f"Front Matter解析失败: {e}")

        return fm, body.strip()

    @staticmethod
    def _extract_slug(fm: dict, file_path: str) -> str:
        """提取 Slug：优先取 FM 的 slug 字段，无则取文件名转拼音后的字符串"""
        slug = None
        for key in ("slug", "title", "subtitle"):
            if key in fm:
                slug = fm[key]
                break
        if slug is None:
            filename = file_path.split("/")[-1]
            slug, _ = os.path.splitext(filename)
        return Pinyin().get_pinyin(slug)

    def _generate_permalink(self, fm: dict, slug: str, file_path: str, file_mtime: float) -> str:
        """
        生成 Permalink

        Args:
            slug: 文章唯一标识
            fm: Front Matter 字典，必须包含 date 字段
            file_path: 文件相对路径 (用于错误提示)
            file_mtime: 文件修改时间戳 (作为 date 的兜底)

        Returns:
            规范化后的 permalink

        Raises:
            ErrorWithPrompt: 遇到不支持的占位符或日期解析失败时抛出
        """

        # 1. 解析日期 (优先级: FM > 文件名 > 文件时间戳)
        pub_date: datetime.datetime | None = None

        # 尝试从 FM 读取
        if "date" in fm:
            try:
                pub_date = datetime.datetime.fromisoformat(str(fm["date"]).split("T")[0])
            except (ValueError, TypeError):
                raise ErrorWithPrompt(
                    f"文章 {file_path} 的 date 字段格式错误\n"
                    f"期望格式: YYYY-MM-DD (如 2026-07-16)\n"
                    f"当前值: {fm.get('date')}"
                )

        # 兜底使用文件修改时间
        if not pub_date:
            pub_date = self._extract_date(file_path, file_mtime)

        # 2. 准备替换映射 (仅支持这三个)
        replacements = {
            ":slug": slug,
            ":year": f"{pub_date.year:04d}",
            ":month": f"{pub_date.month:02d}",
            ":date": f"{pub_date.strftime(DATE_FORMAT)}",
        }

        # 3. 执行替换并校验
        result = fm.get("permalink", self.config.build.permalink)
        for placeholder, value in replacements.items():
            if placeholder in result:
                result = result.replace(placeholder, value)

        # 4. 检查是否还有未处理的占位符 (核心报错逻辑)
        unsupported = re.findall(r':([a-zA-Z_][a-zA-Z0-9_]*)', result)
        if unsupported:
            # 过滤掉我们已经支持的，防止误报
            unsupported = [p for p in unsupported if f":{p}" not in replacements]
            if unsupported:
                raise ErrorWithPrompt(
                    f"配置文件 build.permalink 包含不支持的占位符: :{unsupported[0]}\n"
                    f"当前仅支持: :slug, :year, :month\n"
                    f"请修改 {SITE_CONFIG_FILE} 中的 permalink 规则\n"
                    f"示例: /posts/:year/:month/:slug/"
                )
        # 去掉开头的“/”, 清理双斜杠 (简单处理)
        result = result.lstrip("/").replace("//", "/")

        # 将不可见字符变为-，保留数字、字母和有限字符如"/.-_",并限制前200个字符
        result = normalize_identifier(result)[:200]

        # 如果 permalink 以 "/" 结尾，则追加 "index.html"，否则追加 ".html"
        if result.endswith("/"):
            result = result.rstrip('/') + "/index.html"
        else:
            lower = result.lower()
            if lower.endswith(".htm") or lower.endswith("html"):
                pass
            else:
                result = result + ".html"

        return result

    @staticmethod
    def _extract_date(filepath: str, mtime: float) -> datetime.datetime:
        """
        从文件路径中提取日期（从左往右扫描，找到第一个符合格式的目录/文件名）。
        支持格式：YYYY-MM-DD 或 YYYY_MM_DD
        若未找到，则使用文件修改时间 mtime；若 mtime 无效，则返回 1970-01-01。

        example:
            - /blog/_posts/content/2023_07_10/custom_font_library.md
            - /blog/_posts/content/2023-03-14/modify_nginx.md
        """
        # 1. 从左往右遍历路径中的每一级（包括根目录、各级目录、文件名）
        p = Path(filepath)
        for part in p.parts:
            # 尝试两种日期格式
            for fmt in ("%Y-%m-%d", "%Y_%m_%d"):
                try:
                    return datetime.datetime.strptime(part, fmt)
                except ValueError:
                    continue  # 此部分不匹配，继续尝试下一种格式

        # 2. 若路径中无日期信息，使用文件的修改时间
        try:
            return datetime.datetime.fromtimestamp(mtime)
        except (OSError, ValueError):
            # 3. 终极兜底
            return datetime.datetime.strptime("1970-01-01", "%Y-%m-%d")

    def build_one_post(self, file_path: str, raw_content: str, file_mtime: float) -> Article | None:
        """
        从文件路径和内容构建 Article，在这里只处理渲染流程，不负责如产物搬运等其他流程

        """
        fm, body = self.parse_front_matter(raw_content)
        if not fm:
            raise ErrorWithPrompt("解析Front Matter 错误")
        if fm.get("draft", False) is True:
            raise ErrorWithPrompt("已经设定为 draft")

        # 1. 提取或生成Slug
        slug = self._extract_slug(fm, file_path)

        # 2. 生成目标URL
        dest_url = self._generate_permalink(fm, slug, file_path, file_mtime)
        if not dest_url:
            raise ErrorWithPrompt("未能解析到 permalink")

        # 3. 补充默认元数据
        fm.setdefault("layout", self.config.build.default_layout)
        fm.setdefault("title", slug)
        fm.setdefault("date", self._extract_date(file_path, file_mtime).strftime(DATE_FORMAT))
        # 统一为 str 类型
        if isinstance(fm["date"], (datetime.datetime, datetime.date)):
            fm["date"] = fm["date"].strftime(DATE_FORMAT)

        toc = fm["x-toc"] if "x-toc" in fm else self.config.features.toc
        pipeline = MarkdownRenderPipeline(
            toc=toc,
            highlight_theme="xcode",
            img_base_path=self.config.build.base_path,
        )

        result = pipeline.render_to_html(body)
        return Article(
            src_path=file_path,
            dest_url=dest_url,
            fm=fm,
            raw_content=body,
            rendered_html=result["html"],
            toc=result["toc"],
            images=result["images"],
            code_css=result["css"],
        )
