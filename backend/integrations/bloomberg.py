class BloombergConnector:
    def __init__(self, token: str):
        self.token = token
    def fetch(self, ticker: str):
        raise NotImplementedError

