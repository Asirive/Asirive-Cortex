"""
Saved Locations Manager - Named places for indoor navigation

When GPS is unavailable (indoors), the system needs a starting address
to plan a route. Users pre-configure named locations (Home, School, etc.)
so they can say "I'm at home, navigate to North Point" and the system
uses the saved address as the origin — no GPS required.

Author: Haziq (@IRSPlays)
Date: March 14, 2026
"""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SavedLocations:
    """
    Manages a list of named saved locations with addresses.

    Locations are loaded from config.yaml under layer3.navigation.saved_locations.
    One location can be marked as `default: true` — used automatically when
    the user doesn't specify where they are.

    Supports fuzzy name matching so "relative" matches "Relative's House",
    "granny" matches "Grandma's House", etc.
    """

    def __init__(self, locations_config: List[Dict] = None):
        """
        Args:
            locations_config: List of location dicts from config.yaml, each with:
                - name: Display name (e.g. "Home")
                - address: Full address string
                - aliases: Optional list of alternative names
                - default: Optional bool, True for auto-select when no GPS
        """
        self.locations: Dict[str, Dict] = {}
        self.default_name: Optional[str] = None

        if locations_config:
            for loc in locations_config:
                name = loc.get("name", "").strip()
                if not name:
                    continue
                entry = {
                    "name": name,
                    "address": loc.get("address", ""),
                    "aliases": [a.lower() for a in loc.get("aliases", [])],
                    "default": loc.get("default", False),
                }
                self.locations[name.lower()] = entry
                if entry["default"]:
                    self.default_name = name.lower()

            logger.info(
                f"📍 Loaded {len(self.locations)} saved locations"
                + (f" (default: {self.default_name})" if self.default_name else "")
            )

    def resolve(self, user_input: str) -> Optional[Dict]:
        """
        Match user input to a saved location.

        Tries exact match, then alias match, then substring/fuzzy match.

        Args:
            user_input: What the user said, e.g. "home", "relative's house",
                        "grandma", "9 Canberra Drive"

        Returns:
            Location dict with name/address, or None if no match
        """
        query = user_input.lower().strip()
        if not query:
            return None

        # 1. Exact name match
        if query in self.locations:
            return self.locations[query]

        # 2. Alias match
        for loc in self.locations.values():
            if query in loc["aliases"]:
                return loc

        # 3. Substring match (e.g. "relative" matches "relative's house")
        for key, loc in self.locations.items():
            if query in key or key in query:
                return loc
            for alias in loc["aliases"]:
                if query in alias or alias in query:
                    return loc

        return None

    def get_default(self) -> Optional[Dict]:
        """Get the default location (used when user doesn't specify origin)."""
        if self.default_name and self.default_name in self.locations:
            return self.locations[self.default_name]
        return None

    def get_default_address(self) -> Optional[str]:
        """Get the default location's address string."""
        loc = self.get_default()
        return loc["address"] if loc else None

    def list_names(self) -> List[str]:
        """Get display names of all saved locations."""
        return [loc["name"] for loc in self.locations.values()]

    def list_names_spoken(self) -> str:
        """Get a spoken-friendly list like 'Home, School, or Relative's House'."""
        names = self.list_names()
        if not names:
            return "no saved locations"
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} or {names[1]}"
        return ", ".join(names[:-1]) + f", or {names[-1]}"
