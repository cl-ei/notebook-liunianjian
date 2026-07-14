"""
文件的多版本增量保存逻辑
=========================

目录结构：
  ${STORAGE_ROOT}/{email}/
  ├── storage/               # 用户可见根目录
  │   └── readme.md          # 用户创建的文件
  └── meta/                  # 用户不可见，存放版本历史
      └── readme.md/         # 与 storage 中的文件一一对应
          ├── index.json     # 版本索引
          ├── b1, b2 ...     # 全量基线文件
          └── v1, v2 ...     # 增量版本文件

每个用户文件在 meta 目录下都有一个同名文件夹，
其中包含以下三类文件：

一、index.json — 版本索引

    类型：list[VersionBrief]

    每次保存时追加一条记录，记录本次版本的摘要信息：
    - version     : 对应的版本文件名，如 "v1", "v2"
    - base        : 该版本所依赖的基线文件名，如 "b1"
    - create_time : 提交时间
    - lines       : 本次修改涉及的行数

    用途：快速列出所有历史版本，无需遍历文件。

二、b 文件（b1, b2 ...） — 全量基线文件

    基线文件保存的是某一时刻文件的完整内容。
    首次保存时创建 b1，将全部内容写入。
    之后的版本（v 文件）只记录相对该基线的差异，不再重复存储全文。

    基线的更新策略：
    随着版本数量增加，差异会越积越深，还原时的计算成本也会升高。
    因此在满足以下任一条件时，系统会生成一个新的基线文件：
    - 基于当前基线的版本数量达到 10 个
    - 单次提交的改动行数达到数百行
    - 其他可能造成差异巨大的场景

    新基线创建后，后续的 v 文件将基于这个新基线记录差异，
    不再依赖旧基线。旧基线及其关联的 v 文件不会被删除，
    仍可用于还原历史版本。

三、v 文件（v1, v2 ...） — 增量版本文件

    每次保存生成一个新的 v 文件，编号递增。
    v 文件不存储全文，而是存储一组可重放的差异操作。

    还原方式：
    读取 v 文件对应的基线文件（全量内容），
    然后按顺序执行 v 文件中记录的差异操作，
    即可得到该版本的完整文本。

    关键特性：
    v 文件只依赖基线文件，不依赖其他 v 文件。
    例如 v2 损坏不会影响 v3 的还原，只要基线文件完好即可。
    这意味着损坏是隔离的，不会级联扩散。

    v 文件的结构定义（VersionFile）：
    - base        : 所依赖的基线文件编号，如 1 表示 b1
    - create_time : 提交时间
    - diff        : 差异操作列表（list[DiffItem]），按顺序执行即可还原文本

    DiffItem 结构：
    - count   : 操作影响的行数或字符数
    - added   : 是否为新增内容
    - removed : 是否为删除内容
    - value   : 新增或删除的具体文本内容

    一个 DiffItem 描述一次原子操作：
    - 新增：added=True, value="新增的内容"
    - 删除：removed=True, count=删除的行数
    - 修改：可分解为一次删除 + 一次新增

整体关系总结：
    保存流程：用户保存文件 → 计算与当前基线的差异 → 生成 v 文件 → 更新 index.json
    还原流程：选择版本 → 读取对应基线 → 按序执行 diff → 得到完整文本
    基线更新：满足阈值 → 生成新基线（全文快照）→ 后续版本基于新基线记录

=========================
已废弃的【链式模型】：
    b1 → v1 → v2 → v3 → ...

    链式模型下，每个版本基于前一个版本的差异来存储（v1 → v2 → v3），
    这样做的好处是每次的 diff 始终很小，但存在两个根本性问题：
    1. 脆弱性：任何一个 v 文件损坏，后续所有版本全部无法还原
    2. 读取性能：读取任意版本都需要从 b1 开始依次回放所有差异，
       版本越多读取越慢

这里的存储模型是【星形模型】：
    b1 ─── v1, v2, v3 ... v10
    b2 ─── v11, v12 ... v20
    b3 ─── v21 ...

    每个 v 文件只与基线文件（b 文件）关联，
    v 与 v 之间完全独立，不存在依赖关系。这里解决了链式的两个核心问题：
    - 损坏隔离：v2 损坏不影响 v3，只要基线完好即可独立还原
    - 恒定读取开销：读取任意版本只需加载一个基线和一个 v 文件，
        与版本总数无关，不随历史增长而退化

星型模型的代价是随着版本累积，基线与最新版本之间的差异会越来越深，
导致 diff 体积变大、还原遍历增加。因此引入基线更新机制来截断：
* 当基于同一基线的版本数过多或单次改动过大时，生成新基线，
 将星型结构的中心重新锚定到离最新版本更近的位置。

星型模型下的一个设计推论：
删除操作只记录"删了多少行"，不记录被删除的具体内容。
因为版本回退不需要从当前版本反向推导，直接选择目标版本对应的 v 文
件还原即可。被删除的内容存在于前一版本或基线的还原结果中，在 v 文
件中冗余存储没有必要。
"""

import logging
import datetime
from src.storage.filesystem.local import StorageBackend
from src.storage.path_conf import get_storage, get_user_storage_root, get_user_meta_root
from src import utils
from src.framework.error import ErrorWithPrompt
from .schemas import DiffItem, IndexFile, VersionFile, VersionBrief, FileOpenRespData, DiffResp


def merge_content(base_content: str, diff: list[DiffItem]) -> str:
    result = []
    index = 0
    for d in diff:
        if d.added is True:
            result.append(d.value)
        elif d.removed is True:
            index += d.count
        else:
            result.append(base_content[index: index + d.count])
            index += d.count
    result.append(base_content[index:])
    target_content = "".join(result)
    return target_content


class VersioningAdapter:
    """
    打开文件和保存文件的逻辑
    创建 base 的规则：
    - 初始 base 与该 version 对应，如： b0 <-> v0, b10 <-> v10
    - 当基于某个 base 的 version 超过 10 的时候，rebuild base
    - 当某个 diff 超过 100K 的时候，rebuild base
    """
    def __init__(self, email: str, storage: StorageBackend | None = None):
        if storage is None:
            storage = get_storage()
        self.storage = storage

        self._storage_root = get_user_storage_root(email)
        self._meta_root = get_user_meta_root(email)

    @property
    def storage_root(self) -> str:
        return self._storage_root

    @property
    def meta_root(self) -> str:
        return self._meta_root

    async def _get_latest_version_and_base(self, file: str) -> tuple[int | None, int | None]:
        """
        获取文件的最新版本号和最新基线号

        读取 index.json，遍历所有版本记录，分别取 version 和 base 的最大值。
        注意：最新版本号不一定对应最新基线号，因为版本号始终递增，
        而基线号只在触发基线更新时才跳变。

        若 index.json 不存在（即文件从未保存过版本），返回 (0, 0)，
        与版本号约定保持一致：0 表示无版本记录。

        Params:
            file : 文件相对路径

        Returns:
            (latest_version, latest_base) : 均为 int，无版本记录时返回 (0, 0)
        """
        index_file = f"{self.meta_root}/{file.lstrip('/')}/index.json"
        try:
            file_content = await self.storage.read_text(index_file)
            index_f: IndexFile = IndexFile.model_validate_json(file_content)
        except FileNotFoundError:
            return 0, 0

        last_version = max(v.version for v in index_f.versions)
        last_base = max(v.base for v in index_f.versions)
        return last_version, last_base

    async def _read_version_snapshot(self, file: str, version: int) -> FileOpenRespData:
        """
        按版本号读取文件数据

        根据版本号定位对应的 v 文件，读取其关联的基线内容和增量操作列表。
        前端拿到 base_content 和 diff 后，自行调用 merge_content 还原目标版本的全文。

        版本号约定：
        - version <= 0 时，表示无版本记录，直接读取原始文件，
          返回 version=0, base=0, diff=[]
        - version >= 1 时，去 meta 目录下查找对应的 v 文件及其依赖的基线

        Params:
            file    : 文件相对路径
            version : 目标版本号

        Returns:
            FileOpenRespData:
                - version     : 版本号
                - base        : 该版本依赖的基线编号
                - base_content: 基线文件的全量内容
                - diff        : 增量操作列表，用于前端还原目标版本全文

        Raises:
            ErrorWithPrompt: 文件不存在、版本不存在、基线文件缺失时抛出
        """
        origin_file = f"{self.storage_root}/{file.lstrip('/')}"
        if version <= 0:
            try:
                content = await self.storage.read_text(origin_file)
            except FileNotFoundError:
                raise ErrorWithPrompt("文件不存在")
            return FileOpenRespData(version=0, base=0, base_content=content, diff=[])

        meta_path = f"{self.meta_root}/{file.lstrip('/')}"
        try:
            target_version = f"{meta_path}/v{version}"
            content = await self.storage.read_text(target_version)
            vf = VersionFile.parse_raw(content)
        except FileNotFoundError:
            raise ErrorWithPrompt(f"文件版本({version})不存在")

        # 读取 base 文件
        base_file = f"{meta_path}/b{vf.base}"
        if not await self.storage.exists(base_file) or not await self.storage.is_file(base_file):
            raise ErrorWithPrompt(f"base（{vf.base}）文件不存在")

        try:
            base_content = await self.storage.read_text(base_file)
        except FileNotFoundError:
            raise ErrorWithPrompt("该版本源文件已不存在")

        return FileOpenRespData(version=version, base=vf.base, base_content=base_content, diff=vf.diff)

    async def open_file(self, file: str, version: int = None) -> FileOpenRespData:
        """
        获取文件指定版本的内容

        根据传入的版本号读取对应版本的全量文本。
        若不指定版本号，则返回最新版本。

        版本号约定：
        - version=0 或 base=0 表示"无版本记录"，即 meta 目录尚未建立，
          此时返回原始文件内容，base 和 version 字段均返回 0
        - 真正的版本记录从 1 开始，即 meta 目录中的 b1、v1 等

        Params:
            file    : 文件相对路径
            version : 目标版本号，为 None 时取最新版本，为 0 时返回原始文件

        Returns:
            FileOpenRespData:
                - version     : 返回的版本号
                - base        : 该版本依赖的基线编号
                - base_content: 基线文件的全量内容
                - diff        : 增量操作列表，按序执行可还原目标版本全文

        Raises:
            ErrorWithPrompt: 文件不存在时抛出
        """

        dist = f"{self.storage_root}/{file.lstrip('/')}"

        if not await self.storage.exists(dist) or not await self.storage.is_file(dist):
            raise ErrorWithPrompt("文件不存在")

        if version is None:
            version, _ = await self._get_latest_version_and_base(file)

        return await self._read_version_snapshot(file, version)

    async def save_file_delta(self, file: str, base: int, dst_md5: str, diff: list[DiffItem]) -> tuple[int, int]:
        """
        增量保存文件

        前端计算出用户修改的增量（diff）以及修改后文件的 md5，传入此方法。
        后端会独立还原全量文件并计算 md5，与前端传入值比对，以排除算法差异或异常。

        整体流程：
        1. 读取当前基线内容 → 合并 diff 还原目标内容 → 校验 md5
        2. 对比目标内容与当前最新版本，若相同则跳过保存
        3. 决定是否需要更新基线（满足任一阈值条件则重建）
        4. 写入 v 文件（增量版本）→ 更新 index.json → 返回新版本号和新基线号

        星型模型在此函数中的体现：
        每个 v 文件仅依赖一个基线文件，diff 只记录相对该基线的正向增量。
        当差异累积过深时（达到阈值），生成新基线作为后续版本的锚点，
        新基线 v 文件的 diff 为空，因为它本身就是全量内容的快照。

        Params:
            file     : 文件相对路径，即用户根文件夹下的 node_id
            base     : 当前基线版本号，为 0 表示尚无基线（空文件或上传文件）
            dst_md5  : 前端传入的目标文件 md5，用于校验
            diff     : 前端计算出的增量操作列表

        Returns:
            version : 本次保存后最新的版本号
            base    : 本次保存后使用的基线版本号，前端需缓存此值用于下次提交

        Note:
            diff 中的 count 必须以 Unicode 码元计数，前后端必须统一使用 UTF-8 编码。
            此前出现过 💥 等 emoji 字符因前端 UTF-16 计数导致位置偏移的问题，
            已由前端适配后端标准解决。
        """
        origin_file = f"{self.storage_root}/{file.lstrip('/')}"
        meta_path = f"{self.meta_root}/{file.lstrip('/')}"
        await self.storage.mkdir(meta_path)

        try:
            if base == 0:
                # 如果用户创建空文件，或者上传的文件，没有基线的情况下，读取原文件作为基线。
                # base 为 0 的话在后面会重建基线，将其升为 1，写入新的 b1 基线文件
                base_content = await self.storage.read_text(origin_file)
            else:
                base_file = f"{meta_path}/b{base}"
                base_content = await self.storage.read_text(base_file)
        except FileNotFoundError:
            raise ErrorWithPrompt("无法读取 base 内容")

        target_content = merge_content(base_content, diff)
        result_md5 = utils.calc_md5(target_content)

        if result_md5 != dst_md5:
            logging.info(f"target_content len: {len(target_content)}, "
                         f"dst_md5: {dst_md5}, result_md5: {result_md5}\n "
                         f"content: \n{target_content}\n\n")
            raise ErrorWithPrompt("文件不一致")

        # 读取或还原已经保存的文件内容，若无差异，则无需保存
        version, max_base = await self._get_latest_version_and_base(file)
        fr: FileOpenRespData = await self._read_version_snapshot(file, version)
        old_content = merge_content(base_content=fr.base_content, diff=fr.diff)
        old_md5 = utils.calc_md5(old_content)
        if old_md5 == dst_md5:
            logging.debug(f"on save file delta, md5 not change. file: \n\t{file}")
            return version, max_base

        # 更新原文件
        await self.storage.write_text(origin_file, target_content)

        # 更新base文件
        new_version = version + 1
        now = datetime.datetime.now()
        if (
                base == 0 or
                (new_version > 0 and new_version % 10 == 0) or
                len(diff) > 10 or
                sum([d.count for d in diff if d.added is True or d.removed is True]) > 512
        ):  # 这一步是在有较大改动的时候，重新派生出 base

            # 需要重打基线，直接取 version 相同的版本号，这样在调试时，可以直观看出哪个 v 更新了基线
            new_base = new_version

            # save base file
            await self.storage.write_text(f"{meta_path}/b{new_base}", target_content)

            vf = VersionFile(base=new_base, diff=[], create_time=now)

        else:
            new_base = base
            vf = VersionFile(base=base, diff=diff, create_time=now)

        # 更新version文件
        version_file = f"{meta_path}/v{new_version}"
        await self.storage.write_text(version_file, vf.model_dump_json(ensure_ascii=False))

        # 更新 index file
        index_file = f"{meta_path}/index.json"
        if await self.storage.exists(index_file):
            content = await self.storage.read_text(index_file)
            index_f: IndexFile = IndexFile.model_validate_json(content)
        else:
            index_f = IndexFile()

        index_f.versions.append(VersionBrief(
            version=new_version,
            base=new_base,
            create_time=now,
            lines=len([d for d in diff if d.added is True or d.removed is True])
        ))
        await self.storage.write_text(index_file, index_f.model_dump_json(ensure_ascii=False))
        return new_version, new_base

    async def get_history(self, file: str) -> list[VersionBrief]:
        """
        获取文件的版本历史列表

        读取 index.json，返回所有版本摘要，按版本号降序排列（最新在前）。

        Params:
            file : 文件相对路径

        Returns:
            list[VersionBrief] : 版本摘要列表，各字段含义见 IndexFile 定义

        Raises:
            ErrorWithPrompt: index.json 不存在时抛出（即该文件从未保存过版本）
        """
        index_file = f"{self.meta_root}/{file.lstrip('/')}/index.json"
        try:
            index_content = await self.storage.read_text(index_file)
            data: IndexFile = IndexFile.model_validate_json(index_content)
        except FileNotFoundError:
            raise ErrorWithPrompt("没有版本历史")
        return sorted(data.versions, key=lambda x: x.version, reverse=True)

    async def get_diff(self, file: str, version: int) -> DiffResp:
        """
        获取指定版本与前一版本的内容差异对比

        还原指定版本和前一版本的全文，返回两者内容供前端展示 diff。
        前一版本的查找逻辑：取比当前版本号小的最大可用版本号，
        若无更早版本（如当前为 v1 或之前版本均已缺失），则回退到原始文件（version=0）。

        Params:
            file    : 文件相对路径
            version : 要对比的目标版本号

        Returns:
            DiffResp:
                - prev_version    : 前一版本号，0 表示无版本记录（对比原始文件）
                - prev_content    : 前一版本的全文
                - current_version : 当前（传入的）版本号
                - current_content : 当前版本的全文

        Raises:
            ErrorWithPrompt: index.json 不存在或目标版本不存在时抛出
        """
        index_file = f"{self.meta_root}/{file.lstrip('/')}/index.json"

        try:
            index_content = await self.storage.read_text(index_file)
            index_data: IndexFile = IndexFile.model_validate_json(index_content)
        except FileNotFoundError:
            raise ErrorWithPrompt("没有版本历史")

        version_map: dict[int, VersionBrief] = {v.version: v for v in index_data.versions}
        # 寻找比当前版本稍小一个版本的 version 和 base
        last_version = version - 1
        while last_version > 0:
            if last_version in version_map:
                break
            last_version -= 1

        # 读取旧文件
        f_snap = await self._read_version_snapshot(file, last_version)
        last_content = merge_content(f_snap.base_content, f_snap.diff)

        # 读取新文件
        f_snap_new = await self._read_version_snapshot(file, version)
        cur_content = merge_content(f_snap_new.base_content, f_snap_new.diff)

        return DiffResp(
            prev_version=last_version,
            prev_content=last_content,
            current_version=version,
            current_content=cur_content,
        )

    async def get_latest_file_content(self, file: str) -> str:
        version, _ = await self._get_latest_version_and_base(file=file)
        snap = await self._read_version_snapshot(file, version)
        return merge_content(snap.base_content, snap.diff)


def test():
    data = IndexFile()
    print(f"data: {data}")
    data.versions.append(VersionBrief(
        version=1,
        base=2,
        create_time=datetime.datetime.now(),
    ))


if __name__ == "__main__":
    test()
