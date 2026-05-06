class RateLimitMiddleware:
    def __init__(self, app, rps=10):
        self.app, self.rps = app, rps

