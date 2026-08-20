import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from jinja2 import BaseLoader, Environment, TemplateNotFound
from src.storage.user_fs_adapter import UserFSAdapter


class SpecialIOLoader(BaseLoader):
    def __init__(self,  layouts_root: str, adapter: UserFSAdapter):
        self.adapter = adapter  # 比如数据库 / 网络 / 加密存储客户端
        self.layouts_root = layouts_root

    async def get_source_async(self, environment, template_name):
        """异步获取模板源"""

        try:
            source = await self.adapter.storage.read_text(template_name)
        except Exception as e:
            raise TemplateNotFound(template_name) from e

        if source is None:
            raise TemplateNotFound(template_name)

        # 返回三元组：(source, template_name, uptodate_func)
        result = (source, template_name, lambda: True)
        return result

    def get_source(self, environment, template_name: str):
        """
        返回三元组：(source, template_name, uptodate_func)

        其中，uptodate_func：返回 False 表示模板未变更（缓存用），这里不进行缓存，
        强行返回 True 以避免数据不一致。TODO：当IO呈现压力时，可以在此优化
        """
        if not template_name.startswith(self.layouts_root):
            template_name = f"{self.layouts_root}/{template_name}"

        def wrapped_func():
            return asyncio.run(self.get_source_async(environment, template_name))

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(wrapped_func, )

        result = future.result()
        return result


async def render_layout(layouts_root: str, layout_file: str, context: dict, adapter: UserFSAdapter) -> str:
    env = Environment(
        loader=SpecialIOLoader(layouts_root, adapter),
        trim_blocks=True,  # 移除块（{% %}）后的第一个换行
        lstrip_blocks=True,
    )
    tpl = env.get_template(layout_file)   # 自动拉取 index + layout + 所有依赖
    context["_"] = context
    return tpl.render(context)

