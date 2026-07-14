class NotFound(Exception):
    pass


class Forbidden(Exception):
    pass


class InternalError(Exception):
    pass


class ErrorWithPrompt(Exception):
    def __init__(self, msg: str):
        self.msg = msg
