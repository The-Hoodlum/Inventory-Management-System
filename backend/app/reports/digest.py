"""Per-branch daily digest — what happened at a branch today.

Composes, per branch:
  * SALES + PAYMENTS from the authoritative invoice-based aggregation
    (``ReportsService.get_sales_summary``) — the SAME figures the Daily/Monthly Sales
    Report page shows. There is deliberately no second revenue calculation here: a digest
    that disagreed with the report would be worse than no digest.
  * OPS ACTIVITY counted for the day: order requests raised, transfers dispatched,
    issuances, and bike issues opened.

Everything is per branch, so a branch manager sees THEIR branch — not the whole company.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select

from app.models import BikeIssue, DispatchNote, Issuance, RequestHeader, Warehouse
from app.models.inventory import Branch
from app.reports.service import ReportsService


class DailyDigestService:
    def __init__(self, reports: ReportsService, session) -> None:
        self.reports = reports
        self.session = session

    async def _branches(self) -> list[tuple[uuid.UUID, str]]:
        rows = await self.session.execute(
            select(Branch.id, Branch.name).where(Branch.is_active.is_(True)).order_by(Branch.name)
        )
        return [(bid, name) for bid, name in rows.all()]

    async def _ops_counts(self, day: dt.date) -> dict[uuid.UUID, dict[str, int]]:
        """Per-branch counts of the day's operational activity, one grouped query each."""
        out: dict[uuid.UUID, dict[str, int]] = {}

        def bump(branch_id, key, n) -> None:
            if branch_id is None:
                return
            out.setdefault(branch_id, {})[key] = out.setdefault(branch_id, {}).get(key, 0) + int(n)

        # Order requests are keyed by LOCATION (a warehouse), so resolve to its branch.
        for bid, n in (await self.session.execute(
            select(Warehouse.branch_id, func.count())
            .join(RequestHeader, RequestHeader.branch_id == Warehouse.id)
            .where(func.date(RequestHeader.requested_date) == day)
            .group_by(Warehouse.branch_id)
        )).all():
            bump(bid, "order_requests", n)

        for bid, n in (await self.session.execute(
            select(DispatchNote.from_branch_id, func.count())
            .where(func.date(DispatchNote.created_at) == day)
            .group_by(DispatchNote.from_branch_id)
        )).all():
            bump(bid, "transfers", n)

        for bid, n in (await self.session.execute(
            select(Issuance.branch_id, func.count())
            .where(func.date(Issuance.created_at) == day)
            .group_by(Issuance.branch_id)
        )).all():
            bump(bid, "issuances", n)

        for bid, n in (await self.session.execute(
            select(BikeIssue.branch_id, func.count())
            .where(func.date(BikeIssue.reported_at) == day)
            .group_by(BikeIssue.branch_id)
        )).all():
            bump(bid, "bike_issues", n)

        return out

    async def branch_digests(self, day: dt.date) -> list[dict]:
        """One digest per active branch. Branches with no sales AND no activity are dropped —
        a silent branch should not generate a message saying nothing happened."""
        ops = await self._ops_counts(day)
        digests: list[dict] = []
        for branch_id, branch_name in await self._branches():
            summary = await self.reports.get_sales_summary(
                period="daily", on=day, branch_ids=[branch_id]
            )
            activity = ops.get(branch_id, {})
            sold = [
                {"kind": ln.kind, "ref": ln.ref, "description": ln.description,
                 "qty": ln.qty, "gross": ln.gross}
                for ln in summary.lines
            ]
            payments = [{"method": p.method, "amount": p.amount} for p in summary.payments]
            if not sold and not payments and not activity:
                continue
            digests.append({
                "branch_id": branch_id, "branch": branch_name, "date": day.isoformat(),
                "sold": sold, "payments": payments,
                "gross_total": summary.gross_total,
                "collected_total": summary.collected_total,
                "outstanding_total": summary.outstanding_total,
                "order_requests": activity.get("order_requests", 0),
                "transfers": activity.get("transfers", 0),
                "issuances": activity.get("issuances", 0),
                "bike_issues": activity.get("bike_issues", 0),
            })
        return digests
