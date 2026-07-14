import hashlib
import logging
import re
import asyncio
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
from src.framework.config import BLOG_ROOT, STORAGE_ROOT
from src.storage.blog_adapter import BlogAdapter


class ArticleHeader(BaseModel):
    identity: str = ""
    title: str = ""
    category: str = ""
    description: str = ""
    date: str = ""
    ref: str = ""
    author: str = ""
    tags: List[str] = []

    @validator("identity", pre=True)
    def valid_identity(cls, value: str) -> str:
        result = []
        valid_chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-+._/'
        for c in value:
            if c in valid_chars:
                result.append(c)
        if len(result) == 0:
            raise ValueError(f"Error value: {value}")
        return "".join(result)


class Article(ArticleHeader):
    content: str


class BlogBuilder:

    def __init__(self):
        with open("src/tpl/blog.html", "rb") as f:
            self.tpl = f.read().decode("utf-8")

    def find_all_md_file_under_blog(self, path: str) -> List[str]:
        if not os.path.isdir(path):
            return []
        result = []
        scan_list = [path]
        while scan_list:
            this_path = scan_list.pop(0)
            for file in os.listdir(this_path):
                file: str
                full = os.path.join(this_path, file)
                if os.path.isdir(full):
                    if file.endswith(".meta"):
                        continue
                    scan_list.append(full)
                elif os.path.isfile(full):
                    _, ext = os.path.splitext(file)
                    if ext.lower() != ".md":
                        continue
                    result.append(full)
        return result

    @staticmethod
    def move_image_and_calc_md5(source: str, dist_root: str) -> str:
        path, filename = os.path.split(source)
        base, ext = os.path.splitext(filename)
        temp_file = os.path.join(dist_root, f"{time.time()}_{utils.randstr(16)}")
        utils.safe_make_dir(dist_root)

        buf_size = 8192
        with open(source, 'rb') as fp:
            with open(temp_file, "wb") as wfp:
                md5 = hashlib.md5()
                while True:
                    buf = fp.read(buf_size)
                    if not buf:
                        break
                    md5.update(buf)
                    wfp.write(buf)
            content_md5 = md5.hexdigest()
        target_file_name = f"{content_md5}{ext}"
        target = os.path.join(dist_root, target_file_name)
        os.replace(temp_file, target)

        return target_file_name

    def parse_body(self, email, md_file: Path, body: str, header: ArticleHeader) -> str:
        """
        在这里处理 body，寻找图片、替换路径并移动到static文件夹

        Args
        ----
        email: 从属于的用户
        md_file: 包含绝对路径
        body: md body部分
        header: 此文章的 header
        """
        user, service = email.split("@", 1)
        user_storage_root = Path(STORAGE_ROOT) / email / "storage"
        user_blog_root = Path(BLOG_ROOT) / user / service

        matches = re.findall(r"(!\[[^\n]*?\]\([^\n]+?\))", body)
        replace_map: Dict[str, str] = {}
        for m in matches:
            # m: ![desc](path)
            path_start_index = m.find("](") + 2
            img_path: str = m[path_start_index:-1]

            # 判断 image path, 根据不同情况进行迁移
            # 1. 以 "http://"、"https://" 开头的，直接跳过
            # 2. 以 "/notebook" 起始的图片,直接跳过
            # 3. 其他情况，寻找原图片，计算 md5, 保留扩展名，写入到 "blog_root/img/{{ md5 }}{{ ext }}"
            #       文本替换为: "/notebook/publish/{{ user }}/{{ service }}/img/{{ md5 }}{{ ext }}"

            lp = img_path.lower()
            if lp.startswith("http://") or lp.startswith("https://") or lp.startswith("/notebook"):
                continue
            # 如果是以 "/" 开头，则图片文件在 用户 "storage_root" 下拼接
            # 否则，以当前文档路径下拼接
            if img_path.startswith("/"):
                # 此时 "/" 代表的是用户的 storage root
                physical_img_path = user_storage_root / img_path.lstrip("/")
            else:
                # 这种情况，![](href) 中的 href 是与 md 同级的文件
                physical_img_path = md_file.parent / img_path

            if not physical_img_path.exists() or not physical_img_path.is_file():
                logging.debug(f"cannot find file: {physical_img_path}")
                continue

            file_name = self.move_image_and_calc_md5(
                source=str(physical_img_path),
                dist_root=str(user_blog_root / "img"),
            )
            img_uri = f"/notebook/publish/{user}/{service}/img/{file_name}"
            replace_map[m] = m[:path_start_index] + img_uri + ")"

        for origin, rep in replace_map.items():
            body = body.replace(origin, rep)
        return body

    @staticmethod
    def parse_header(header: str) -> Dict:
        valid_keys = set(ArticleHeader().dict().keys())
        create_param = {}
        lines = header.split("\n")
        for line in lines:
            kv = line.split(":", 1)
            if len(kv) != 2:
                continue
            key = kv[0].strip(" ")
            if key not in valid_keys:
                continue
            value = kv[1].strip(" ")
            if key == "tags":
                value = [v.strip() for v in value.split(",")]
            create_param[key] = value
        return create_param

    def parse_one_md(self, email: str, md_file: Path, write_root: Path) -> Optional[Article]:
        """
        解析博客

        1. 解析一篇文章，写 html
        2. 返回 meta
        """
        raise NotImplementedError()

        user_storage_root = Path(STORAGE_ROOT) / email / "storage"

        inner_file = data_io.openfile(email=email, file=str(md_file.relative_to(user_storage_root)))
        content = data_io.merge_content(inner_file.base_content, inner_file.diff)
        inner = content.strip("\r\n").lstrip("---").lstrip("\r\n")
        try:
            split_index = inner.index("---")
        except ValueError:
            return None

        header_str, body = inner[:split_index], inner[split_index + 3:].lstrip("\r\n")

        header_dict = self.parse_header(header_str)
        if "date" not in header_dict:
            modify_time = os.path.getmtime(md_file)
            header_dict["date"] = datetime.datetime.fromtimestamp(modify_time).strftime('%Y-%m-%d')
        if "title" not in header_dict:
            _, filename = os.path.split(md_file)
            header_dict["title"] = filename.split(".", 1)[0]
        if "category" not in header_dict:
            header_dict["category"] = "未分类"
        article_id = Pinyin().get_pinyin(f"{header_dict['date']}/{header_dict['title']}")
        header = ArticleHeader(identity=article_id, **header_dict)

        base, _ = os.path.split(md_file)
        parsed_body = self.parse_body(email, md_file, body, header)
        article = Article(content=parsed_body, **header.dict())

        # 写 html
        user, service = email.split("@", 1)
        html_content = jinja2.Template(self.tpl).render({
            "page": "article",
            "article": article,
            "user": user,
            "service": service,
        })
        dist_html_file = os.path.join(write_root, f"{article.identity}.html")
        html_rel_path, _ = os.path.split(dist_html_file)
        utils.safe_make_dir(html_rel_path)
        with open(dist_html_file, "wb") as f:
            f.write(html_content.encode("utf-8", errors="replace"))
        return article

    def gen_category(self, write_root: str, articles: List[Article], user: str, service: str):
        # 准备 context
        articles.sort(key=lambda x: x.date, reverse=True)
        cat_map: Dict[str, List] = {}
        for art in articles:
            cat_map.setdefault(art.category, []).append(art)

        categories: List[Tuple[str, List[Article]]] = [(cat_name, art_li) for cat_name, art_li in cat_map.items()]
        categories.sort(key=lambda x: x[0])

        # 写 html
        html_content = jinja2.Template(self.tpl).render({
            "page": "category",
            "categories": categories,
            "user": user,
            "service": service,
        })
        dist_html_file = os.path.join(write_root, f"category.html")
        with open(dist_html_file, "wb") as f:
            f.write(html_content.encode("utf-8", errors="replace"))

    def gen_home_and_about(self, write_root: str, articles: List[Article], user: str, service: str):
        # 准备 context
        articles.sort(key=lambda x: x.date, reverse=True)

        # 写 home
        html_content = jinja2.Template(self.tpl).render({
            "page": "home",
            "articles": articles[:10],
            "user": user,
            "service": service,
        })
        dist_html_file = os.path.join(write_root, f"index.html")
        with open(dist_html_file, "wb") as f:
            f.write(html_content.encode("utf-8", errors="replace"))

        # 写 about
        html_content = jinja2.Template(self.tpl).render({"page": "about", "user": user, "service": service})
        dist_html_file = os.path.join(write_root, f"about.html")
        with open(dist_html_file, "wb") as f:
            f.write(html_content.encode("utf-8", errors="replace"))

    def do_generate(self, email: str):
        """

        1. 创建 BLOG_ROOT/{email_user}/{service}/version.txt
        2. 找寻所有的 md 文件
        """
        # 存放生成好的静态资源的额 root 目录
        user, service = email.split("@", 1)
        write_root = Path(BLOG_ROOT) / user / service
        logging.debug(f"start generate blog html files for email: {email}, write to ->\n\t{write_root}")
        try:
            shutil.rmtree(str(write_root))
        except:  # noqa
            pass
        write_root.mkdir(exist_ok=True, parents=True)
        version_file = write_root / "version.txt"
        version_file.touch(exist_ok=True)
        version_file.write_text(str(datetime.datetime.now()))

        # 寻找所有的 md 文件 并为每个md生成html
        all_article_list: List[Article] = []
        source_root = Path(STORAGE_ROOT) / email / "storage" / "blog"
        for md_file in source_root.rglob("*.md"):
            # md_file 包含绝对路径
            logging.debug(f"process md_file: {md_file}")
            meta = self.parse_one_md(email, md_file, write_root)
            if not meta:
                continue
            all_article_list.append(meta)

        # 生成 category 页
        self.gen_category(write_root, all_article_list, user, service)

        # 生成首页
        self.gen_home_and_about(write_root, all_article_list, user, service)


async def publish_blog(email: str, version: str = "") -> bool:
    """
    将用户的 email 文件夹下所有 md 转化为 html

    BLOG_ROOT/{email_user}/{service}/version.txt  此文件夹下的文件名代表刷新 blog 时的时间戳
    BLOG_ROOT/{email_user}/{service}/index.html  此文件夹下
    """
    logging.info(f"start publish blog: {email}")
    await asyncio.sleep(10)
    adapter = BlogAdapter(email)
    return await adapter.set_version(version)
