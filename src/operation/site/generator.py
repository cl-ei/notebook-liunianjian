import copy
import hashlib
import logging
import traceback
from asyncio.queues import Queue
import re
import yaml
import datetime
import os.path
import shutil
import time
from pathlib import Path
import jinja2
from typing import *
from pydantic import BaseModel, validator
from xpinyin import Pinyin
from src import utils
from src.framework.error import ErrorWithPrompt
from src.operation.site.schema import SiteConfig, Article, SITE_CONFIG_FILE
from src.storage.user_fs_adapter import UserFSAdapter
from src.operation.site.parsing import ArticleBuilder
from src.operation.site.templating import render_layout


async def parse_user_site_config(email: str) -> SiteConfig:
    """
    解析用户站点配置文件

    Args:
        email: 用户 email

    Returns:
        SiteConfig: 解析后的配置对象

    Raises:
        ErrorWithPrompt: 配置解析错误时抛出友好提示
    """
    adapter = UserFSAdapter(email)
    site_config_file = f"{adapter.storage_root.rstrip('/')}/{SITE_CONFIG_FILE}"
    if not await adapter.storage.exists(site_config_file) or not await adapter.storage.is_file(site_config_file):
        raise ErrorWithPrompt(
            f"配置文件不存在。\n\n"
            f"请在站点根目录创建 {SITE_CONFIG_FILE} 文件。\n"
            f"可参考示例配置：_site_config.example.yaml"
        )
    try:
        content = await adapter.storage.read_text(site_config_file)
    except:  # noqa
        raise ErrorWithPrompt("配置文件内容错误")

    try:
        try:
            config_dict = yaml.safe_load(content)
        except yaml.YAMLError as e:
            # 提取更友好的YAML错误信息
            error_line = ""
            if hasattr(e, 'problem_mark'):
                mark = e.problem_mark
                error_line = f"（第 {mark.line + 1} 行，第 {mark.column + 1} 列）"

            raise ErrorWithPrompt(
                f"配置文件语法错误{error_line}：\n"
                f"{str(e)}\n\n"
                f"常见原因：\n"
                f"1. 冒号后缺少空格（正确：'key: value'，错误：'key:value'）\n"
                f"2. 缩进使用Tab键（请使用空格）\n"
                f"3. 字符串包含特殊字符未加引号\n"
                f"4. 列表项格式错误\n\n"
                f"可参考示例配置：_site_config.example.yaml"
            )

    except Exception as e:
        raise ErrorWithPrompt(
            f"无法读取配置文件：{str(e)}\n\n"
            f"请检查文件权限或路径是否正确。"
        )

    # 4. 检查配置内容是否为空
    if not config_dict:
        raise ErrorWithPrompt(
            f"配置文件为空或格式不正确。\n\n"
            f"请确保文件包含有效的YAML配置内容。\n"
            f"可参考示例配置：_site_config.example.yaml"
        )

    # 5. 使用Pydantic V2解析配置
    try:
        site_config = SiteConfig.model_validate(config_dict)  # V2 语法：model_validate
        return site_config

    except ErrorWithPrompt:
        # 直接重新抛出我们自定义的验证错误
        raise
    except Exception as e:
        # 处理Pydantic验证错误
        if hasattr(e, 'errors'):
            # Pydantic验证错误，格式化错误信息
            error_messages = []
            for error in e.errors():
                field_path = ' → '.join(str(loc) for loc in error['loc'])
                message = error['msg']

                # 提供更友好的字段描述
                if 'site' in error['loc']:
                    if 'name' in error['loc']:
                        message = "站点名称不能为空，请设置 site.name"
                    elif 'url' in error['loc']:
                        message = "站点URL不能为空，请设置 site.url"

                error_messages.append(f"字段 '{field_path}': {message}")

            formatted_errors = '\n'.join(f"  • {msg}" for msg in error_messages)
            raise ErrorWithPrompt(
                f"配置文件验证失败，发现 {len(error_messages)} 个问题：\n\n"
                f"{formatted_errors}\n\n"
                f"请修正以上问题后重试。\n"
                f"可参考示例配置：_site_config.example.yaml"
            )
        else:
            # 其他未知错误，不暴露内部细节
            raise ErrorWithPrompt(
                f"配置文件解析失败，请检查格式是否正确。\n\n"
                f"可参考示例配置：_site_config.example.yaml"
            )


def is_markdown_file(filename: str) -> bool:
    """
    Markdown文件过滤器，支持常见扩展名、大小写不敏感、自动排除临时文件
    支持的扩展名覆盖：
    - 标准扩展名：.md/.markdown
    - 常用别名：.mdown/.mkd/.mkdn/.mdwn/.mdtxt
    - 生态扩展名：.mdx(RMarkdown)/.rmd(RStudio)/.jmd(Julia)/.qmd(Quarto)/.litmd(Literate)
    """
    # 支持的Markdown扩展名集合（frozenset保证O(1)查找效率+不可变性）
    md_extensions = frozenset({
        '.md', '.markdown',          # 最通用标准扩展名
        '.mdown', '.mkd', '.mkdn', '.mdwn', '.mdtxt',  # 历史别名/小众变种
        '.mdx',                      # React MDX
        '.rmd',                      # R Markdown
        '.jmd',                      # Julia Markdown
        '.qmd',                      # Quarto Markdown
        '.litmd',                    # Literate Markdown
    })

    # 需排除的临时/备份文件后缀（避免编辑器生成的临时文件被误判）
    excluded_suffixes = frozenset({'~', '.bak', '.swp', '.swap', '.tmp'})

    # 空文件名直接排除
    if not filename:
        return False

    # 排除隐藏文件（以.开头的文件，如.config.md，可按需调整）
    if filename.startswith('.'):
        return False

    # 排除临时/备份文件
    if any(filename.endswith(suffix) for suffix in excluded_suffixes):
        return False

    # 提取扩展名（转小写，兼容Windows/macOS/Linux的大小写差异）
    file_ext = Path(filename).suffix.lower()
    return file_ext in md_extensions


class StaticSiteGenerator:
    def __init__(self, email: str):
        self.email = email
        self.adapter = UserFSAdapter(email)
        self.err_q: Queue = Queue()

        self._config: SiteConfig | None = None
        self._write_root: str = ""
        self._layouts_root: str = ""

    async def load_config(self) -> SiteConfig:
        if self._config is None:
            self._config = await parse_user_site_config(self.email)
        return self._config

    @property
    def write_root(self) -> str:
        if self._write_root:
            return self._write_root

        if not self._config:
            raise ErrorWithPrompt("配置不正确，未能获取 write_root")

        write_root = "%s/%s/%s" % (self.adapter.storage_root, self._config.build.source_root.strip('/'), "_build")
        self._write_root = self.adapter.resolve(write_root)
        return self._write_root

    @property
    def layouts_root(self) -> str:
        if self._layouts_root:
            return self._layouts_root

        if not self._config:
            raise ErrorWithPrompt("配置不正确，未能获取 layouts_root")
        layouts_root = "%s/%s/%s" % (self.adapter.storage_root, self._config.build.source_root, "_layouts")
        self._layouts_root = self.adapter.resolve(layouts_root)
        return self._layouts_root

    def record_log(self, msg: str):
        self.err_q.put_nowait(f"{datetime.datetime.now()} {msg}")

    async def _do_generate(self, config: SiteConfig):
        logging.info(f"start generate static site: {self.email}")

        # 清除输出目录，移动static目录
        write_root = self.write_root
        if (await self.adapter.storage.exists(write_root) and
                await self.adapter.storage.is_dir(write_root)):
            await self.adapter.storage.remove_tree(write_root)

        self.record_log(f"{SITE_CONFIG_FILE} 加载成功。")

        statics_dir = "%s/%s" % (self.adapter.storage_root, config.build.statics_dir)
        if config.build.statics_dir and \
                await self.adapter.storage.exists(statics_dir) and \
                await self.adapter.storage.is_dir(statics_dir):
            await self.adapter.copy_tree(src=statics_dir, dst=write_root)
            self.record_log(f"静态文件拷贝成功。")
        else:
            self.record_log(f"跳过拷贝静态文件。")

        # 扫描所有Markdown文件
        # 有两种生成方式：
        # 1. 全部读取、转换、构建context，然后挨个渲染，可能会在文章过多时造成内存占用过高。目前
        #   使用此方法生成。
        # 2. 第一遍扫描所有文章的元信息，再挨个读取文章的content、转换、构建context，然后
        #   挨个渲染。能够控制内存占用，后续可以按此法优化。
        posts_path = f"{config.build.source_root.rstrip('/')}/_posts"
        all_files: list[str] = await self.adapter.find_files(posts_path, is_markdown_file)
        self.record_log(f"已获取posts总数：{len(all_files)}。")

        # 构建文章列表，解析基础信息
        article_builder = ArticleBuilder(config, self.adapter.storage_root)
        all_posts: dict[str, list[Article]] = {}  # layout -> [articles...]
        for file_path in all_files:
            try:
                # 读取源文件
                full_path = f"{self.adapter.storage_root}/{file_path.lstrip('/')}"
                raw_content = await self.adapter.storage.read_text(full_path)
                filesize, file_mtime = await self.adapter.storage.stat(full_path)

                # 构建Article对象
                try:
                    article: Article = article_builder.build_one_post(file_path, raw_content, file_mtime)
                except ErrorWithPrompt as e:
                    self.record_log(f"文件{file_path}解析时发生错误：{e.msg}。")
                    continue
                except Exception as e:
                    logging.error(f"error happened when build one post: {e}\n{traceback.format_exc()}")
                    self.record_log(f"文件{file_path}解析时发生错误。")
                    continue

                # 套用模板
                layout_name = article.fm["layout"]

                layout_filename = layout_name if layout_name.endswith(".html") else f"{layout_name}.html"
                layout = f"{self.layouts_root}/{layout_filename}"
                if not await self.adapter.storage.exists(layout):
                    self.record_log(f"未找到文件{file_path}声明的layout “{layout_name}”，跳过处理。")
                    continue

                all_posts.setdefault(layout_name, []).append(article)
            except Exception as e:
                self.record_log(f"在解析{file_path}时发生错误：{e}。")
                print(f"parse one error: {e}\n{traceback.format_exc()}")
                # 继续处理其他文件，不中断构建
                continue

        # 聚合数据
        context = {"site": config.site.model_dump()}
        user_defined_layouts: list[str] = []
        tags_map: dict[str, list] = {}
        categories_map: dict[str, list] = {}
        for layout_name, articles in all_posts.items():
            articles.sort(key=lambda a: a.fm.get("date", ""), reverse=True)
            for i, article in enumerate(articles):
                article.index = i

            user_defined_layouts.append(layout_name)
            context[layout_name] = [a.model_dump() for a in articles]

            for data in context[layout_name]:
                sa: dict = copy.deepcopy(data)
                for key in ("raw_content", "rendered_html", "toc", "images", "code_css"):
                    sa.pop(key)
                for tag in sa["fm"].get("tags", []):
                    tags_map.setdefault(tag, []).append(sa)

                raw_cate = sa["fm"].get("category")
                if isinstance(raw_cate, str):
                    categories_map.setdefault(raw_cate, []).append(sa)
                elif isinstance(raw_cate, (list, tuple)):
                    for cate in raw_cate:
                        categories_map.setdefault(cate, []).append(sa)
        context["tags"] = tags_map
        context["categories"] = categories_map

        user, service = self.email.split("@", 1)
        context["email"] = self.email
        context["user"] = user
        context["service"] = service

        # 写入文件，移动产物
        for layout_name in user_defined_layouts:
            for post in context[layout_name]:
                ctx = copy.deepcopy(context)
                ctx["this"] = copy.deepcopy(post)
                ctx["_ctx"] = ctx

                layout_filename = layout_name if layout_name.lower().endswith(".html") else f"{layout_name}.html"
                layout = f"{self.layouts_root}/{layout_filename}"
                try:
                    final_html = await render_layout(
                        layouts_root=self.layouts_root,
                        layout_file=layout,
                        context=ctx,
                        adapter=self.adapter,
                    )
                except jinja2.exceptions.TemplateNotFound:
                    self.record_log(f"未找到layout文件“{layout_name}”，跳过处理：{post['src_path']}。")
                    continue

                except jinja2.exceptions.UndefinedError as e:
                    self.record_log(f"渲染文件{post['src_path']}时出错：{e}, 已跳过。")
                    continue

                except jinja2.exceptions.TemplateSyntaxError as e:
                    self.record_log(f"渲染文件{post['src_path']}时检测到模板格式错误：{e}, 已跳过。")
                    continue

                # 写入文件
                # 分两步，避免 permalink 为“/”或空，导致生成包含非预期的“//”的问题
                dst_folder = "%s/%s" % (write_root, post["dest_url"].strip('/'))
                filepath = dst_folder.rstrip("/") + "/index.html"
                await self.adapter.storage.write_text(filepath, final_html)
                self.record_log(f"已生成：{post['dest_url']}。")

                # 进行静态资源的迁移
                md_src = "%s/%s" % (self.adapter.storage_root, post["src_path"].strip('/'))
                count = await self.copy_images(md_src, filepath, post["images"])
                self.record_log(f"已处理 {count} 个图像对象。")

        print("generate complete!\n")

    async def copy_images(self, md_src: str, md_dst: str, images: list[dict]) -> int:
        """
        迁移 md文件关联的图片文件，分三种情况：

        # ![alt](./a.jpg)      → 相对当前页面，将图片挪动到相对于当前文件的路径下
        # ![alt](/a.jpg)       → 相对站点根目录 _build/ 下）
        # ![alt](https://...)  → 不做任何处理

        Args:
            md_src: str, md 文件所在路径，是包括 storage_root 的绝对路径
            md_dst: str, md 文件渲染的 html 的目标位置，是包括 storage_root 的绝对路径
            images: list[dict], 元素为 ImageRef 结构: {
                'src': 'board.jpg',
                'alt': '',
                'title': '',
            }
        """
        proc_count = 0
        if not images:
            return proc_count

        img_src_list: list[str] = [a['raw'] for a in images]
        logging.info(f"start copy image files, src_path: {md_src}, total: {len(img_src_list)}")
        for img_path in img_src_list:
            for scheme in {'http', 'https', 'ftp', 'ftps', 'data', 'blob', 'file'}:
                if img_path.startswith(scheme):
                    continue

            if img_path.startswith("/"):
                img_src = "%s/%s" % (self.adapter.storage_root, img_path.lstrip('/'))
                img_dst = "%s/%s" % (self.write_root, img_path.lstrip('/'))

                logging.debug(f"copy img file by abs way:\n"
                              f"\timg_src:  {img_src}\n"
                              f"\timg_dst: {img_dst}")
            else:
                # 相对路径的情况
                source_parent = os.path.split(md_src)[0]
                dst_parent = os.path.split(md_dst)[0]

                img_src = "%s/%s" % (source_parent, img_path)
                img_dst = "%s/%s" % (dst_parent, img_path)

                logging.debug(f"copy img file by rel way:\n"
                              f"\tsource:  {img_src}\n"
                              f"\tdest: {img_dst}")

            if await self.adapter.storage.exists(img_src) and \
                    await self.adapter.storage.is_file(img_src):
                await self.adapter.storage.copy(img_src, img_dst)
                logging.debug(f"source img copy success: {img_src}")
            else:
                logging.warning(f"source img not exist: {img_src}")
            proc_count += 1

        return proc_count

    async def gen(self):
        # 加载配置
        config: SiteConfig | None = None

        try:
            config = await self.load_config()
            await self._do_generate(config)
        except ErrorWithPrompt as e:
            self.record_log(f"发生错误：{e.msg}。")
        except Exception as e:
            logging.error(f"error happened in _do_generate: {e}\n{traceback.format_exc()}")
            self.record_log(f"发生未知错误。")
        finally:
            if config is None:
                logging.error(f"cannot load site config of user: {self.email}")
                return

            self.record_log(f"生成结束。")
            log_file = "%s/build.log" % self.write_root
            contents = []
            while not self.err_q.empty():
                contents.append(self.err_q.get_nowait())
            await self.adapter.storage.write_text(log_file, '\n'.join(contents))
