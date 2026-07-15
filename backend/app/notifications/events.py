"""Event-type identifiers for notifications. Producers pass these to the service; they're
generic strings (the core knows nothing about assembly) but named here so producers stay
consistent and the set is discoverable."""
from __future__ import annotations

# Assembly (first producers — sell-before-assembly feature)
BIKE_SOLD_BEFORE_ASSEMBLY = "bike.sold_before_assembly"
BIKE_ASSEMBLED = "bike.assembled"
BIKE_DISPATCHED_UNASSEMBLED = "bike.dispatched_unassembled"
