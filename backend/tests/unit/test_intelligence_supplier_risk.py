"""Unit tests for supplier-risk scoring."""
from __future__ import annotations

from decimal import Decimal

from app.intelligence.domain.supplier_risk import SupplierMetrics, supplier_risk

D = Decimal


def test_perfect_supplier_is_low_risk():
    m = SupplierMetrics(on_time_rate=1.0, avg_lead_time_days=30, lead_time_stdev_days=1,
                        fill_rate=1.0, received_po_count=20)
    r = supplier_risk(m)
    assert r.risk_score < D("0.05")
    assert r.reliability > D("0.95")


def test_late_deliveries_drive_risk():
    m = SupplierMetrics(on_time_rate=0.5, avg_lead_time_days=None, lead_time_stdev_days=None,
                        fill_rate=None, received_po_count=8)
    r = supplier_risk(m)
    # only the 'late' component is present -> weight renormalises to 1.0 -> risk = 0.5
    assert r.components == {"late": D("0.5000")}
    assert r.risk_score == D("0.5000")
    assert any("On-time" in reason for reason in r.reasons)


def test_lead_time_variance_component():
    m = SupplierMetrics(on_time_rate=1.0, avg_lead_time_days=30, lead_time_stdev_days=15,
                        fill_rate=1.0, received_po_count=5)
    r = supplier_risk(m)
    assert r.components["variance"] == D("0.5000")  # cov = 15/30
    assert any("volatile" in reason for reason in r.reasons)


def test_no_history_is_neutral():
    m = SupplierMetrics(on_time_rate=None, avg_lead_time_days=None, lead_time_stdev_days=None,
                        fill_rate=None, received_po_count=0)
    r = supplier_risk(m)
    assert r.risk_score == D("0")
    assert r.reliability == D("1")
    assert r.reasons == ["No delivery history"]


def test_combined_components_are_weighted():
    # late=0.4 (w .4), fill=0.2 (w .3), variance=0.0 (w .3)
    # risk = (0.4*0.4 + 0.2*0.3 + 0.0*0.3) / (0.4+0.3+0.3) = (0.16+0.06)/1.0 = 0.22
    m = SupplierMetrics(on_time_rate=0.6, avg_lead_time_days=30, lead_time_stdev_days=0,
                        fill_rate=0.8, received_po_count=12)
    r = supplier_risk(m)
    assert r.risk_score == D("0.2200")
