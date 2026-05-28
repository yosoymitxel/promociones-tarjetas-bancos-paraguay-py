from __future__ import annotations

from .scrapers import (
    ItaúScraper,
    ContinentalScraper,
    EClubScraper,
    PersonalPayScraper,
    GNBScraper,
    BASAScraper,
)

SCRAPERS = {
    "basa": BASAScraper,
    "eclub": EClubScraper,
    "gnb": GNBScraper,
    "itau": ItaúScraper,
    "continental": ContinentalScraper,
    "personalpay": PersonalPayScraper,
}