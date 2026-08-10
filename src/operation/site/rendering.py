import hashlib
import re
import contextvars
from pathlib import Path
from typing import List, Dict, Any
import nh3
import mistune
from mistune import HTMLRenderer
from mistune.plugins.math import math, math_in_quote, math_in_list
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.styles import get_style_by_name, STYLE_MAP
from pygments.util import ClassNotFound
from markupsafe import escape as html_escape

from src.operation.site.schema import ImageRef, TocItem


# ---------------------- TOC ----------------------------

UGC_TAGS = {
    'p', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'strong', 'em', 'del', 'blockquote',
    'a', 'img', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
}

PIPELINE_TAGS = UGC_TAGS | {
    'pre', 'code', 'span', 'div',     # 代码高亮 + 数学公式容器
    'details', 'summary',             # 折叠块
    'sup', 'sub',                     # 数学上下标
}

PIPELINE_ATTRS: dict[str, set[str]] = {
    "*":     {"class", "id"},
    "a":     {"href", "title", "target"},
    "img":   {"src", "alt", "width", "height", "loading", "decoding", "srcset", "sizes", "referrerpolicy"},
    "pre":   {"data-language"},
    "code":  {"data-language"},
    "td":    {"colspan", "rowspan", "align"},
    "th":    {"colspan", "rowspan", "align"},
}


def clean_ugc_html(raw_html: str) -> str:
    """UGC 内容净化入口。"""
    return nh3.clean(
        raw_html,
        tags=PIPELINE_TAGS,
        attributes=PIPELINE_ATTRS,
        url_schemes={"http", "https", "mailto"},
        link_rel="nofollow noopener noreferrer",  # ✅ 自动为所有 <a> 注入 rel
        strip_comments=True,
    )


# ⚠️ 防御性绑定：math_in_quote / math_in_list 必须与 math 同时启用。
# 它们负责在引用块和列表的子解析器中注册数学语法规则。
# 当前版本默认行为恰好包含这些规则，但这属于未文档化的内部实现细节，
# mistune 升级可能随时移除。显式声明可避免公式在特定上下文中静默失效。
MATH_PLUGINS = [math, math_in_quote, math_in_list]


# 预制开关表（列表保序，元组定义默认值）
# 顺序已按照 mistune v3 安全加载顺序排列
PLUGIN_REGISTRY: List[tuple[str, bool]] = [
    ("speedup",       True),   # 性能优化，必开
    ("table",         True),   # GFM 表格，基线功能
    ("def_list",      False),  # 定义列表，按需
    ("footnotes",     True),   # 脚注，高频需求
    ("task_lists",    True),   # 任务列表，基线功能
    ("math",          True),   # 数学公式，高频需求
    ("strikethrough", True),   # 删除线，基线功能
    ("mark",          False),  # 高亮标记，按需
    ("insert",        False),  # 下划线/插入，按需
    ("superscript",   False),  # 上标，易冲突，按需
    ("subscript",     False),  # 下标，易冲突，按需
    ("spoiler",       False),  # 剧透折叠，按需
    ("abbr",          False),  # 缩写提示，按需
    ("ruby",          False),  # 注音排版，窄众
    ("url",           True),   # 自动链接，放最后防误伤
]

# 预计算合法插件名集合，用于 O(1) 校验
_VALID_PLUGIN_NAMES = {name for name, _ in PLUGIN_REGISTRY}


# 使用 context var 保证并发/多次调用时的状态隔离
_image_collector: contextvars.ContextVar[List[ImageRef]] = contextvars.ContextVar(
    '_image_collector', default=[]
)

# 匹配 <img> 标签中的 src 和 alt 属性（不区分大小写，允许单引号/双引号/无引号）
_IMG_TAG_RE = re.compile(
    r'<img\s[^>]*?\bsrc\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))[^>]*/?>',
    re.IGNORECASE | re.DOTALL
)
_IMG_ALT_RE = re.compile(
    r'\balt\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(\S+))',
    re.IGNORECASE
)


class CollectingRenderer(HTMLRenderer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._formatter: HtmlFormatter | None = None  # 默认为 None
        self._used_math: bool = False

        # TOC 状态
        self._toc_enabled = True
        self._toc_items: List[TocItem] = []

        self._anchor_counts: dict[str, int] = {}  # 用于锚点去重
        self._img_base_path: str = ""

        # lazy_load
        self._lazy_load_enabled = True
        self._rel_to_storage_root = ""
        self._dst_path = ""

    def set_formatter(self, formatter: HtmlFormatter):
        self._formatter = formatter

    def set_toc(self, enable: bool):
        self._toc_enabled = enable

    def set_img_base_path(self, img_base_path: str):
        self._img_base_path = img_base_path

    def set_lazy_load(self, enable: bool):
        self._lazy_load_enabled = enable

    def set_rel_to_storage_root(self, path: str):
        self._rel_to_storage_root = path

    def set_dst_path(self, path: str):
        self._dst_path = path

    @property
    def toc(self) -> List[TocItem]:
        return list(self._toc_items)  # 返回副本

    @property
    def toc_enabled(self) -> bool:
        return self._toc_enabled

    @property
    def used_math(self) -> bool:
        return bool(self._used_math)

    @used_math.setter
    def used_math(self, used: bool):
        self._used_math = used

    def reset(self):
        self._used_math = False
        self._toc_items.clear()
        self._anchor_counts.clear()

    @staticmethod
    def _slugify(text: str) -> str:
        text = str(html_escape(text)).lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)        # 移除特殊字符
        text = re.sub(r'[\s_]+', '-', text)         # 空格/下划线转连字符
        text = re.sub(r'-+', '-', text).strip('-')  # 去除连续连字符
        base = text or 'heading'

        if base and all('\u4e00' <= c <= '\u9fff' for c in base.replace('-', '')):
            short_hash = hashlib.md5(base.encode()).hexdigest()[:6]
            return f"{base}-{short_hash}"
        return base

    def heading(self, text: str, level: int, **attrs) -> str:
        # 无论是否开启 TOC，都要正常渲染 heading HTML
        if self._toc_enabled:
            # 注意：text 此时可能包含内联 HTML（如 <code>），需提取纯文本用于 TOC
            plain_text = re.sub(r'<[^>]+>', '', text)
            base_anchor = self._slugify(plain_text)
            count = self._anchor_counts.get(base_anchor, 0)
            anchor = f"{base_anchor}-{count}" if count > 0 else base_anchor
            self._anchor_counts[base_anchor] = count + 1

            self._toc_items.append(TocItem(
                level=level,
                text=plain_text,
                anchor=anchor
            ))

            # 将锚点注入到 heading 的 id 属性中，保证正文与 TOC 可联动
            attrs['id'] = anchor

        return super().heading(text, level, **attrs)

    def image(self, text: str, url: str, title: str | None = None) -> str:
        """
        解析 ![]() 的地址，统一转化为绝对路径引用方式

        """
        collector = _image_collector.get()

        if not url:
            url_class = ""
        elif url.startswith(("https://", "http://", "//", "file://", "data:", "blob:", "#", "?")):
            url_class = "protocol"
        elif url.startswith("/"):
            url_class = "abs"
        else:
            url_class = "rel"

        # 只处理绝对路径和相对路径的情况，方便进行静态资源迁移
        if url_class == "abs":  # 绝对路径
            path = url
            url = self._img_base_path + url
        elif url_class == "rel":  # 相对路径
            path = self._rel_to_storage_root + "/" + url
            url = self._img_base_path + self._dst_path.rstrip('/') + "/" + f"{url}"
        else:
            path: str = ""

        collector.append(ImageRef(path=path, href=url, alt=text, title=title or ""))

        # ⚠️ 关键：仍然调用父类方法生成正常 HTML，不改变渲染输出
        content = super().image(text, url, title)
        if self._lazy_load_enabled and 'loading="lazy"' not in content and content.endswith(" />"):
            content = content.removesuffix(" />") + ' loading="lazy" decoding="async" />'
        return content

    def block_html(self, raw: str) -> str:
        self._collect_img_from_raw_html(raw)
        return super().block_html(raw)

    def inline_html(self, raw: str) -> str:
        self._collect_img_from_raw_html(raw)
        return super().inline_html(raw)

    def _collect_img_from_raw_html(self, raw: str) -> None:
        """
        一个 raw_html 节点可能包含多个 <img>（虽然罕见），
        所以用 finditer 而非 search。
        """
        _ = self
        for match in _IMG_TAG_RE.finditer(raw):
            # src 在三组捕获中取第一个非 None
            src = next((g for g in match.groups() if g is not None), "")

            # 提取 alt
            alt_match = _IMG_ALT_RE.search(match.group())
            alt = ""
            if alt_match:
                alt = next((g for g in alt_match.groups() if g is not None), "")

            _image_collector.get().append(
                ImageRef(path="", href=src, alt=alt, title=None)
            )

    def block_code(self,  code: str, info: str | str = None) -> str:
        if self._formatter is None:
            return super().block_code(code, info)

        lang = (info or "").strip().split()[0] if info else ""
        try:
            lexer = get_lexer_by_name(lang) if lang else guess_lexer(code)
        except ClassNotFound:
            escaped = mistune.escape(code)
            return f'<pre><code>{escaped}</code></pre>\n'

        return highlight(code, lexer, self._formatter)


class MarkdownRenderPipeline:
    """
    配置在构造时注入，采集结果随 render 返回。
    线程安全，可复用于多文档渲染。
    但在多个文章的初始化参数不同时，应当重新初始化，或以参数为 key 进行复议

    """
    def __init__(
            self,
            *,
            rel_path_to_storage_root: str,       # 当前处理的文章路径，参考 storage_root 的相对路径
            dst_path_to_build_root: str,         # 目标路径，相对于 build_root
            toc: bool = True,
            lazy_load: bool = True,
            plugins: dict[str, bool] = None,
            img_base_path: str = "",
            highlight_linenos: bool = False,     # 默认开启行号
            highlight_stripnl: bool = False,     # 保留空行语义
            highlight_theme: str = "default",    # Pygments 内置主题名或自定义 Style 类
    ):
        plugins = plugins or {}
        # 严格校验：检查是否有预期外的插件参数
        unexpected = set(plugins.keys()) - _VALID_PLUGIN_NAMES
        if unexpected:
            supported = ", ".join(sorted(_VALID_PLUGIN_NAMES))
            raise ValueError(
                f"Unsupported plugin(s): {unexpected}. "
                f"Supported plugins are: [{supported}]"
            )

        # 按注册表顺序遍历，用户指定优先，否则走默认值
        active_plugins: List[str] = []
        for plugin_name, default_enabled in PLUGIN_REGISTRY:
            # 用户显式传入了该参数（无论 True/False），一律听从用户
            if plugin_name in plugins:
                if plugins[plugin_name]:
                    active_plugins.append(plugin_name)
            # 用户未指定，按照预制表的默认配置决定
            elif default_enabled:
                active_plugins.append(plugin_name)

        self._plugins = active_plugins

        # 构建 Pygments Formatter
        if highlight_theme not in STYLE_MAP:
            raise ValueError(
                f"Unknown Pygments theme: '{highlight_theme}'. \n"
                f"Available choices: {', '.join(STYLE_MAP.keys())}"
            )
        style = get_style_by_name(highlight_theme)

        self._formatter = HtmlFormatter(
            cssclass="code-highlight",
            cssprefix="ph-",
            nowrap=False,
            noclasses=False,
            linenos=highlight_linenos,
            stripnl=highlight_stripnl,
            style=style,
        )

        renderer = CollectingRenderer(escape=False)
        renderer.set_formatter(self._formatter)
        renderer.set_toc(toc)
        renderer.set_lazy_load(lazy_load)
        renderer.set_img_base_path(img_base_path)
        renderer.set_rel_to_storage_root(rel_path_to_storage_root)
        renderer.set_dst_path(dst_path_to_build_root)

        self._markdown = mistune.create_markdown(
            renderer=renderer,
            plugins=self._plugins,
        )

        # patch math
        if "math" in active_plugins:
            def render_block_math(rd, text: str) -> str:
                rd.used_math = True
                return f'<div class="math-block">{text}</div>\n'

            def render_inline_math(rd, text: str) -> str:
                rd.used_math = True
                return f'<span class="math-inline">{text}</span>'

            md = self._markdown
            md.renderer.register("block_math", render_block_math)
            md.renderer.register("inline_math", render_inline_math)

    @property
    def active_plugins(self) -> List[str]:
        """暴露当前生效的插件列表，方便调试和序列化配置"""
        return list(self._plugins)

    def render_to_html(self, content: str) -> Dict[str, Any]:
        """
        渲染 Markdown 并同步返回采集到的图片引用。

        Returns:
            {
                "html": "<p>...</p>",
                "css": ".xxx",
                "images": [ImageRef(path="...", href="...", alt="..." ...), ...],
                "used_math": bool,
                "toc": [TocItem(level=1, ... ), ...]
            }
        """
        # 为本次调用创建独立的收集容器
        collected: List[ImageRef] = []
        token = _image_collector.set(collected)

        try:
            # 重置 renderer 状态
            self._markdown.renderer.reset()  # noqa

            html = self._markdown(content)
            safe_html = clean_ugc_html(html)
            renderer: CollectingRenderer = self._markdown.renderer  # noqa
            data = {
                "html": safe_html,
                "css": self._formatter.get_style_defs('.code-highlight'),
                "images": list(collected),  # 返回副本防止外部修改
                "used_math": renderer.used_math,
                "toc": renderer.toc,
            }

            return data
        finally:
            # 无论成功失败都清理上下文，避免内存泄漏
            _image_collector.reset(token)


def test():
    base_dir = Path(__file__).resolve().parent
    md_path = base_dir / "test.md"
    html_path = base_dir / "preview.html"

    if not md_path.exists():
        print(f"❌ 未找到 {md_path}")
        return

    pipeline = MarkdownRenderPipeline(
        plugins={
            "table": True,
            "strikethrough": True,
        },
        highlight_theme="xcode",
    )

    md_content = md_path.read_text(encoding="utf-8")
    result = pipeline.render_to_html(md_content)

    # ✅ CSS 内联，生成完全自包含的预览文件
    html_output = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Preview - {md_path.stem}</title>
<style>
  body {{
    max-width: 800px;
    margin: 2rem auto;
    padding: 0 1rem;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.6;
    color: #333;
  }}
  img {{ max-width: 100%; height: auto; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #f5f5f5; }}
  pre {{ overflow-x: auto; }}
    pre {{
    /* 1. 字体：等宽字体的选择决定了 80% 的质感 */
    font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 
                 'SF Mono', 'Consolas', monospace;
    
    /* 2. 字号 & 行高：Pygments 默认值通常偏小偏挤 */
    font-size: 14px;          /* 推荐 13-15px */
    line-height: 1.6;         /* 推荐 1.5-1.7，默认 1.2 太挤 */
    
    /* 3. 内边距：给代码呼吸空间 */
    padding: 1em 1.2em;       /* 默认往往只有 0.5em */
    
    /* 4. 圆角 & 阴影：现代感的来源 */
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
    
    /* 5. 横向滚动而非换行 */
    overflow-x: auto;
    white-space: pre;         /* 确保不换行 */
    
    /* 6. 可选：行号对齐、tab 宽度 */
    tab-size: 4;
}}
  /* Pygments 代码高亮样式 */
  {result["css"]}
</style>
</head>
<body>
{result["html"]}
</body>
</html>"""

    html_path.write_text(html_output, encoding="utf-8")

    print(f"✅ 预览已生成: {html_path}")
    print(f"   采集到 {len(result['images'])} 张图片:")
    for img in result["images"]:
        print(f"     src={img.src!r}  alt={img.alt!r}  title={img.title!r}")

    print(f"used math?: {result['used_math']}")
    print("show toc")
    for item in result["toc"]:
        level = item['level']
        print(f"{'    '*(level - 1)}{item}")


if __name__ == "__main__":
    test()
