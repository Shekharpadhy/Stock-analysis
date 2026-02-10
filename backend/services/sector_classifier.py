GICS_MAP = {
    "Energy": {
        "sub_sectors": ["Oil & Gas Exploration", "Oil & Gas Refining", "Coal & Consumable Fuels", "Renewable Energy"],
        "keywords": ["energy", "oil", "gas", "petroleum", "fuel", "coal", "pipeline", "refin"],
    },
    "Materials": {
        "sub_sectors": ["Chemicals", "Metals & Mining", "Paper & Forest Products", "Construction Materials"],
        "keywords": ["chemical", "mining", "metal", "steel", "aluminum", "paper", "forest", "cement"],
    },
    "Industrials": {
        "sub_sectors": ["Aerospace & Defense", "Industrial Machinery", "Transportation", "Building Products"],
        "keywords": ["defense", "aerospace", "machinery", "transport", "logistics", "railroad", "construction"],
    },
    "Consumer Discretionary": {
        "sub_sectors": ["Automobiles", "Retail", "Hotels & Restaurants", "Media & Entertainment"],
        "keywords": ["auto", "vehicle", "retail", "restaurant", "hotel", "media", "entertainment", "apparel"],
    },
    "Consumer Staples": {
        "sub_sectors": ["Food & Beverages", "Household Products", "Personal Products", "Drug Retail"],
        "keywords": ["food", "beverage", "grocery", "household", "personal care", "tobacco", "drug store"],
    },
    "Health Care": {
        "sub_sectors": ["Pharmaceuticals", "Biotechnology", "Medical Devices", "Health Care Services"],
        "keywords": ["pharma", "biotech", "medical", "health", "hospital", "drug", "clinical", "therapeutics"],
    },
    "Financials": {
        "sub_sectors": ["Banking", "Insurance", "Capital Markets", "Consumer Finance", "REITs"],
        "keywords": ["bank", "insurance", "capital", "finance", "lending", "credit", "mortgage", "invest", "reit"],
    },
    "Information Technology": {
        "sub_sectors": ["Software", "Hardware", "Semiconductors", "IT Services", "Cloud & Data"],
        "keywords": ["software", "hardware", "semiconductor", "chip", "cloud", "data", "tech", "internet", "saas"],
    },
    "Communication Services": {
        "sub_sectors": ["Telecom", "Interactive Media", "Broadcasting", "Wireless Services"],
        "keywords": ["telecom", "wireless", "broadcast", "media", "social", "network", "communication"],
    },
    "Utilities": {
        "sub_sectors": ["Electric Utilities", "Gas Utilities", "Water Utilities", "Multi-Utilities"],
        "keywords": ["utility", "electric", "power", "water", "renewable", "grid"],
    },
    "Real Estate": {
        "sub_sectors": ["Diversified REITs", "Industrial REITs", "Office REITs", "Residential REITs"],
        "keywords": ["real estate", "reit", "property", "residential", "commercial", "office"],
    },
}


def classify_sector(yahoo_sector: str, industry: str) -> tuple[str, str]:
    combined = f"{yahoo_sector} {industry}".lower()

    for sector, config in GICS_MAP.items():
        for kw in config["keywords"]:
            if kw in combined:
                sub = _match_sub_sector(config["sub_sectors"], combined)
                return sector, sub

    if yahoo_sector and yahoo_sector != "Unknown":
        return yahoo_sector, industry or "General"

    return "Unclassified", "Unknown"


def _match_sub_sector(sub_sectors: list[str], text: str) -> str:
    for sub in sub_sectors:
        if any(word.lower() in text for word in sub.split()):
            return sub
    return sub_sectors[0]


def get_sector_peers(sector: str, all_companies: list[dict]) -> list[dict]:
    return [c for c in all_companies if c.get("sector") == sector]
