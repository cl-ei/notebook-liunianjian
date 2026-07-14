import uuid


class GlobalLock:
    """
    全局锁, 原本使用 Redis setnx 命令来加锁，在结束的时候借住 lua 再判断
    一次锁是否是自己加的，若是，则释放。为移除 Redis 依赖，此为空实现

    Parameters
    ----------
    name: str
        锁的名. 区分不能同时进行的操作的最小粒度的 key

    lock_time: int
        锁定的时间. 一般适用于很短就能完成的场景，长时间
        的任务不推荐使用这种办法，因为中途若发生譬如 worker
        重启等异常，则持有的锁在超时时间内不能开锁。

    try_times: int = 3
        尝试加锁的次数。若置为 0，则会反复加锁，直到获取到锁。
        0 值应当慎用，会产生大量 Redis 请求.

    _retry_interval: float, seconds
        在每次加锁失败后，休眠的时间，最小 0.1 秒
    """
    key_prefix = "LOCK:"

    def __init__(
            self,
            name: str,
            lock_time: int = 5,
            try_times: int = 3,
            _retry_interval: float = 0.3
    ):
        self.key = f"{self.key_prefix}:{name}"
        self.lock_time = lock_time
        self.try_times = try_times
        self._retry_interval = max(0.1, _retry_interval)

        self.__locked: bool = False
        self.__identification: str = f"{uuid.uuid4()}"

    async def __aenter__(self):
        self.__locked = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.__locked = False

    @property
    def locked(self) -> bool:
        return self.__locked
