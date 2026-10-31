from dataclasses import dataclass

from flightbot.config import Settings
from flightbot.providers.base import PriceProvider
from flightbot.providers.names import PlaceNames
from flightbot.providers.places import PlacesProvider


@dataclass(frozen=True, slots=True)
class Deps:
    """Handler-lərə yeridilən xidmətlər (aiogram workflow data: `deps`)."""

    provider: PriceProvider
    places: PlacesProvider
    names: PlaceNames
    settings: Settings
