class AppError(Exception):
    def __init__(self, msg: str, code: int = 400):
        self.msg = msg; self.code = code; super().__init__(msg)

class NotFoundError(AppError):
    def __init__(self, resource: str):
        super().__init__(f"{resource} not found", 404)

class AuthError(AppError):
    def __init__(self, msg: str = "Unauthorized"):
        super().__init__(msg, 401)

class RateLimitError(AppError):
    def __init__(self):
        super().__init__("Too many requests", 429)
