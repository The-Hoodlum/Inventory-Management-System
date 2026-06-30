"""Import targets. Importing this package registers every built-in target."""
from app.imports.targets import inventory as _inventory  # noqa: F401  (registers)
from app.imports.targets import suppliers as _suppliers  # noqa: F401  (registers)
from app.imports.targets import warehouses as _warehouses  # noqa: F401  (registers)
