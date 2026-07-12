"""Import targets. Importing this package registers every built-in target."""
from app.imports.targets import inventory as _inventory  # noqa: F401  (registers)
from app.imports.targets import motorcycle_units as _motorcycle_units  # noqa: F401  (registers)
from app.imports.targets import opening_balances as _opening_balances  # noqa: F401  (registers)
from app.imports.targets import parts_sales_log as _parts_sales_log  # noqa: F401  (registers)
from app.imports.targets import stock_reconciliation as _stock_reconciliation  # noqa: F401  (registers)
from app.imports.targets import stock_replay as _stock_replay  # noqa: F401  (registers)
from app.imports.targets import suppliers as _suppliers  # noqa: F401  (registers)
from app.imports.targets import warehouses as _warehouses  # noqa: F401  (registers)
