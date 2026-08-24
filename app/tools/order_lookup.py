"""Safe, deterministic lookup over the mock order snapshot."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OrderItem:
    name: str
    quantity: int
    final_sale: bool


@dataclass(frozen=True)
class CustomerSafeOrder:
    order_id: str
    membership_tier: str
    items: tuple[OrderItem, ...]
    placed_at: str
    status: str
    status_updated_at: str
    shipped_at: str | None
    delivered_at: str | None
    carrier: str | None
    tracking_number: str | None
    estimated_delivery: str | None
    customer_safe_message: str


@dataclass(frozen=True)
class OrderLookupResult:
    found: bool
    order: CustomerSafeOrder | None = None
    error: str | None = None
    requires_human_review: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        if self.order is not None:
            result["order"] = asdict(self.order)
        return result


class OrderLookupTool:
    """Load the dataset once and expose only an explicit safe schema."""

    def __init__(self, orders_path: Path) -> None:
        self.orders_path = orders_path
        self._orders_by_id = self._load_orders(orders_path)

    @staticmethod
    def _load_orders(orders_path: Path) -> dict[str, dict[str, Any]]:
        with orders_path.open("r", encoding="utf-8") as handle:
            dataset = json.load(handle)
        orders = dataset.get("orders")
        if not isinstance(orders, list):
            raise ValueError("orders.json must contain an orders list")
        return {
            str(order["order_id"]).strip().upper(): order
            for order in orders
            if isinstance(order, dict) and order.get("order_id")
        }

    def lookup_order(self, order_id: str) -> OrderLookupResult:
        normalized_id = order_id.strip().upper()
        if not normalized_id:
            return OrderLookupResult(False, error="order_id_required", requires_human_review=False)

        raw_order = self._orders_by_id.get(normalized_id)
        if raw_order is None:
            return OrderLookupResult(False, error="order_not_found", requires_human_review=True)

        status = str(raw_order["status"]).lower()
        suppress_shipping = status in {"cancelled", "returned"}
        safe_order = CustomerSafeOrder(
            order_id=str(raw_order["order_id"]),
            membership_tier=str(raw_order["membership_tier"]),
            items=tuple(
                OrderItem(
                    name=str(item["name"]),
                    quantity=int(item["quantity"]),
                    final_sale=bool(item["final_sale"]),
                )
                for item in raw_order.get("items", [])
            ),
            placed_at=str(raw_order["placed_at"]),
            status=status,
            status_updated_at=str(raw_order["status_updated_at"]),
            shipped_at=None if suppress_shipping else raw_order.get("shipped_at"),
            delivered_at=raw_order.get("delivered_at"),
            carrier=None if suppress_shipping else raw_order.get("carrier"),
            tracking_number=None if suppress_shipping else raw_order.get("tracking_number"),
            estimated_delivery=None if suppress_shipping else raw_order.get("estimated_delivery"),
            customer_safe_message=str(raw_order["customer_safe_message"]),
        )
        return OrderLookupResult(
            found=True,
            order=safe_order,
            requires_human_review=status == "exception",
        )


_DEFAULT_TOOL: OrderLookupTool | None = None


def lookup_order(order_id: str, orders_path: Path | None = None) -> OrderLookupResult:
    """Look up one order, using the repository dataset by default."""
    global _DEFAULT_TOOL
    path = orders_path or Path(__file__).parents[2] / "data" / "orders.json"
    if _DEFAULT_TOOL is None or _DEFAULT_TOOL.orders_path != path:
        _DEFAULT_TOOL = OrderLookupTool(path)
    return _DEFAULT_TOOL.lookup_order(order_id)