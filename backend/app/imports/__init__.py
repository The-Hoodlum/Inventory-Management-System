"""Generic, reusable data-import framework.

A target-agnostic engine (parse → auto-detect columns → map → validate → preview →
import) plus a registry of ``ResourceImporter`` targets. Inventory is the first
target; suppliers, customers, sales history, POs, etc. plug in the same way. The
pure, DB-free machinery lives in ``domain/`` (unit-tested in isolation); DB-bound
orchestration lives in ``repository.py`` / ``service.py`` / ``api.py``.
"""
