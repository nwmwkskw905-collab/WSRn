import pytest


def test_ads_default_budget_is_zero(db):
    from jarvis.modules.ads import get_ads

    policy = get_ads().budget_policy()
    assert policy["enabled"] is False
    assert policy["daily_limit_brl"] == 0.0


def test_ads_budget_requires_approval(db):
    from jarvis.modules.ads import get_ads

    with pytest.raises(PermissionError):
        get_ads().set_budget_policy(50, 500, "act_123")


def test_ads_prepare_costs_nothing_and_flags_budget(db):
    from jarvis.modules.ads import get_ads

    result = get_ads().prepare("Vender curso de fotografia", daily_budget=100, monthly_limit=300)
    assert result["spent_brl"] == 0.0
    assert result["published"] is False
    assert result["plan"]["budget"]["guard_errors"]
    assert result["plan"]["status"] == "blocked_budget"


def test_ads_publish_without_approval_blocked(db):
    from jarvis.modules.ads import get_ads, AdsError
    import asyncio

    campaign = get_ads().prepare("Teste", daily_budget=0)
    with pytest.raises(PermissionError):
        asyncio.run(get_ads().publish_meta(campaign["campaign_id"], None))


def test_ads_metrics_math_and_sample_warning(db):
    from jarvis.modules.ads import get_ads

    analysis = get_ads().analyze([
        {"campaign_id": "c1", "spend": 100, "impressions": 10000, "clicks": 200, "conversions": 5, "revenue": 500},
        {"campaign_id": "c2", "spend": 20, "impressions": 1000, "clicks": 10, "conversions": 0, "revenue": 0},
    ], target_cpa=20)
    first, second = analysis["campaigns"]
    assert first["cpc_brl"] == 0.5
    assert first["cpa_brl"] == 20.0
    assert first["roas"] == 5.0
    assert second["confidence"] == "insuficiente"


def test_sales_report_separates_pending_and_refunds(db):
    from jarvis.modules.sales import get_sales

    db.execute("DELETE FROM orders")
    rows = [
        ("o1", "paid", 10000, "2026-10-18T00:00:00Z", {"fees": 6.0}),
        ("o2", "paid", 5000, "2026-10-18T00:00:00Z", {"fees": 3.0}),
        ("o3", "waiting_payment", 7000, "2026-10-18T00:00:00Z", {}),
        ("o4", "refunded", 10000, "2026-10-18T00:00:00Z", {"fees": 6.0}),
    ]
    for i, (oid, status, cents, paid_at, raw) in enumerate(rows):
        db.execute(
            "INSERT INTO orders(id, provider, provider_order_id, status, amount_cents, created_at, paid_at, raw_json)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (f"local-{i}", "cakto", oid, status, cents, "2026-10-18T00:00:00Z", paid_at, __import__("json").dumps(raw)),
        )
    report = get_sales().order_summary(3650)
    assert report["paid_orders"] == 2
    assert report["pending_orders"] == 1
    assert report["refunded_orders"] == 1
    assert report["gross_revenue_brl"] == 150.0
    assert report["refunds_brl"] == 100.0
    assert report["fees_brl"] == 15.0
    assert report["net_revenue_estimate_brl"] == 35.0
    assert "Pix gerado" in " ".join(report["notes"])


def test_sales_empty_report_is_honest(db):
    from jarvis.modules.sales import get_sales

    db.execute("DELETE FROM orders")
    report = get_sales().order_summary(7)
    assert report["is_empty"] is True
    assert report["gross_revenue_brl"] == 0.0


def test_crm_consent_gate(db):
    from jarvis.modules.sales import get_sales

    service = get_sales()
    service.create_lead("Sem consentimento", "a@b.com", consent=False)
    service.create_lead("Com consentimento", "c@d.com", consent=True)
    eligible = service.eligible_contacts()
    assert [e["email"] for e in eligible] == ["c@d.com"]


def test_business_unit_economics():
    from jarvis.modules.business import get_business

    econ = get_business().unit_economics(price=100, target_monthly_revenue=1000, conversion_rate=0.02,
                                         ad_cost_per_click=1.0, payment_fee_percent=5, refund_rate=0.1)
    assert econ["inputs"]["price"] == 100
    assert econ["math"]["cac_estimate"] == 50.0
    assert econ["math"]["customers_needed_for_target"] == 10
    assert econ["math"]["traffic_needed_for_target"] == 500
    assert econ["classification"]["traffic_needed_for_target"].startswith("estimativa")
