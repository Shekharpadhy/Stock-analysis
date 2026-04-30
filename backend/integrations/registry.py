from .bloomberg import BloombergConnector
from .refinitiv import RefinitivConnector

CONNECTORS = {'bloomberg': BloombergConnector, 'refinitiv': RefinitivConnector}

