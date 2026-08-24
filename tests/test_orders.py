from pathlib import Path

from app.tools.order_lookup import lookup_order


ORDERS = Path(__file__).parents[1] / "data" / "orders.json"


def get_order(order_id: str):
    result = lookup_order(order_id, ORDERS)
    assert result.found
    assert result.order is not None
    return result.order


def test_valid_order_returns_customer_safe_fields() -> None:
    order = get_order("ORD-1007")
    assert order.status == "shipped"
    assert order.carrier == "UPS"
    assert order.estimated_delivery == "2026-08-22"
    assert order.items[0].name == "Atlas Weekender"


def test_order_id_matching_is_case_insensitive() -> None:
    assert get_order("ord-1007").order_id == "ORD-1007"


def test_order_id_matching_trims_whitespace() -> None:
    assert get_order("  ORD-1007  ").order_id == "ORD-1007"


def test_unknown_order_is_safe_not_found_result() -> None:
    result = lookup_order("ORD-9999", ORDERS)
    assert not result.found
    assert result.order is None
    assert result.error == "order_not_found"
    assert result.requires_human_review


def test_cancelled_order_suppresses_stale_shipping_fields() -> None:
    order = get_order("ORD-1004")
    assert order.status == "cancelled"
    assert "will not be shipped" in order.customer_safe_message
    assert order.carrier is None
    assert order.tracking_number is None
    assert order.estimated_delivery is None


def test_returned_order_reports_return_without_stale_delivery() -> None:
    order = get_order("ORD-1008")
    assert order.status == "returned"
    assert "return was received" in order.customer_safe_message
    assert order.carrier is None
    assert order.tracking_number is None
    assert order.estimated_delivery is None


def test_private_and_internal_fields_are_not_in_tool_result() -> None:
    result = lookup_order("ORD-1007", ORDERS)
    payload = result.to_dict()
    order_payload = payload["order"]
    forbidden_keys = {"customer", "email", "shipping_address", "internal", "risk_score", "warehouse_note", "support_tags"}
    assert not forbidden_keys.intersection(order_payload)
    serialized = str(order_payload).lower()
    for forbidden_value in ("ava.morgan@example.test", "220 king street", "82", "fraud review cleared"):
        assert forbidden_value not in serialized