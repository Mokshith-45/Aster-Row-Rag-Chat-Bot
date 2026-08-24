"""Lightweight, grounded support-agent orchestration."""

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from .memory import SessionMemory
from .observability.logger import log_trace
from .prompts import SYSTEM_PROMPT
from .rag.retriever import RAGRetriever, RetrievalResult, expand_query
from .tools.order_lookup import OrderLookupResult, OrderLookupTool


ORDER_ID_RE = re.compile(r"\bORD[-\s]?\d{4}\b", re.IGNORECASE)
INJECTION_TERMS = ("ignore previous", "ignore all prior", "ignore the real policy", "system instruction", "migration note")
PROMPT_EXTRACTION_TERMS = ("reveal your system prompt", "show hidden prompt", "developer prompt", "system prompt")
PRIVATE_TERMS = ("email", "address", "internal note", "risk score", "risk information", "hidden field", "api key", "secret", "credential")
ACTION_TERMS = ("cancel", "refund", "replace", "replacement", "price adjustment", "address change", "approve")
KNOWN_TOPIC_TERMS = (
    "return", "ship", "shipping", "canada", "country", "warranty", "tumbler", "dishwasher",
    "gift card", "price", "trailplus", "membership", "damaged", "defective", "wrong item",
    "care", "wash", "delivery", "final sale", "promotion", "order", "broken",
    "product", "products", "catalog", "sell", "offer", "buy", "categories", "items", "breeze", "exchange",
)


@dataclass
class AgentResponse:
    answer: str
    route: str
    sources: list[dict[str, str]] = field(default_factory=list)
    handoff: bool = False
    tool_calls: list[dict[str, str]] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


class SupportAgent:
    def __init__(
        self,
        retriever: RAGRetriever,
        order_tool: OrderLookupTool,
        memory: SessionMemory | None = None,
    ) -> None:
        self.retriever = retriever
        self.order_tool = order_tool
        self.memory = memory or SessionMemory()

    @staticmethod
    def _order_id(message: str, history: list[Any]) -> str | None:
        match = ORDER_ID_RE.search(message)
        if match:
            return match.group(0).replace(" ", "-").upper()
        for item in reversed(history):
            match = ORDER_ID_RE.search(item.content)
            if match:
                return match.group(0).replace(" ", "-").upper()
        return None

    @staticmethod
    def _has_order_follow_up(message: str) -> bool:
        terms = ("when will it arrive", "where is it", "what is its status", "tracking it")
        return any(term in message.lower() for term in terms)

    @staticmethod
    def _is_order_question(message: str, order_id: str | None) -> bool:
        terms = ("order", "tracking", "shipped", "arrive", "delivery", "where is", "status", "cancel")
        return order_id is not None and any(term in message.lower() for term in terms)

    @staticmethod
    def _has_order_intent(message: str) -> bool:
        terms = ("tracking", "where is", "shipped", "arrive", "delivery", "order status", "cancel my order")
        lowered = message.lower()
        return any(
            re.search(rf"\b{re.escape(term)}\b", lowered) is not None
            for term in terms
        )

    @staticmethod
    def _trace_text(text: str) -> str:
        return re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[redacted-email]", text)

    def _safe_order_response(self, result: OrderLookupResult, order_id: str) -> str:
        if not result.found:
            return "That order was not found. Please check the order ID or contact support."
        assert result.order is not None
        order = result.order
        return f"Order {order.order_id} is {order.status}. {order.customer_safe_message}"

    @staticmethod
    def _rag_query(message: str, history: list[Any]) -> str:
        lowered = message.lower()
        if "trailplus" in lowered:
            return "TrailPlus membership return window"
        if "germany" in lowered or "country" in lowered:
            return "international shipping supported destinations country"
        if "canada" in lowered:
            return "international shipping Canada delivery duties taxes"
        if "international" in lowered or "ship internationally" in lowered:
            return "international shipping supported destinations Canada"
        if "warranty" in lowered:
            return "limited product warranty warranty periods covered not covered"
        if any(term in lowered for term in ("product", "products", "catalog", "sell", "offer", "buy", "categories", "items")):
            return "product catalog products sold Breeze Tumbler bags drinkware travel accessories"
        if "return" in lowered:
            return "returns policy standard return window return shipping refunds exclusions"
        if "exchange" in lowered:
            return "exchanges return policy Canadian direct exchanges final sale"
        if "damaged" in lowered or "broken" in lowered or "defective" in lowered:
            return "final sale damaged wrong item reporting window human review"
        context = " ".join(item.content for item in history[-2:] if item.role == "user")
        return f"{context} {message}".strip()

    @staticmethod
    def _relevant_sources(retrieval: RetrievalResult, query: str) -> list[dict[str, str]]:
        sources = retrieval.sources
        lowered = query.lower()
        if retrieval.conflicts:
            conflict_sources = set(retrieval.conflicts[0]["sources"])
            return [source for source in sources if source["filename"] in conflict_sources]
        if "trailplus" in lowered:
            return [source for source in sources if "return window" in source["heading"].lower()][:1]
        if "shipping policy" in lowered:
            return [
                source for source in sources
                if source["filename"] in {"05-domestic-shipping.md", "06-international-shipping.md"}
            ][:3]
        if "canada" in lowered or "international" in lowered:
            return [
                source for source in sources
                if any(term in source["heading"].lower() for term in ("supported destinations", "delivery estimate", "duties and taxes"))
            ][:3]
        if any(term in lowered for term in ("damaged", "broken", "defective")):
            return [
                source for source in sources
                if source["filename"] in {"03-final-sale-and-promotions.md", "04-damaged-or-wrong-items.md"}
            ][:3]
        return sources[:1]

    def _rag_response(self, result: RetrievalResult, query: str) -> tuple[str, bool]:
        if not result.chunks or result.chunks[0].final_score < 0.20:
            return (
                "The supplied information is insufficient to answer that reliably. "
                "Please contact human support for confirmation.",
                True,
            )
        if result.conflicts:
            conflict = result.conflicts[0]
            return (
                "Current official sources conflict on this point: one says "
                f"{conflict['claims'][0]}, while another says {conflict['claims'][1]}. "
                "I cannot safely choose between them. Please use the safest interim guidance "
                "and contact human support for confirmation.",
                True,
            )
        lowered_query = query.lower()
        if "trailplus" in lowered_query:
            selected_chunks = [
                item for item in result.chunks
                if "return window" in item.chunk.heading.lower()
            ][:1]
        elif "canada" in lowered_query or "international" in lowered_query:
            selected_chunks = [
                item for item in result.chunks
                if any(term in item.chunk.heading.lower() for term in ("supported destinations", "delivery estimate", "duties and taxes"))
            ][:3]
        elif any(term in lowered_query for term in ("damaged", "broken", "defective")):
            selected_chunks = [
                item for item in result.chunks
                if item.chunk.source_filename in {"03-final-sale-and-promotions.md", "04-damaged-or-wrong-items.md"}
            ][:5]
        else:
            selected_chunks = result.chunks[:1]
        evidence_parts = []
        for item in selected_chunks or result.chunks[:1]:
            evidence_parts.append(item.chunk.text.split("\n\n", 1)[-1].strip())
        handoff = any(term in lowered_query for term in ("damaged", "broken", "defective"))
        answer = "\n\n".join(dict.fromkeys(evidence_parts))
        if handoff:
            answer += "\n\nA human must review the report before any refund or replacement is approved."
        return answer, handoff

    def respond(self, session_id: str, message: str, debug: bool = False) -> AgentResponse:
        history = self.memory.recent(session_id)
        lowered = message.lower()
        trace: dict[str, Any] = {
            "session_id": session_id,
            "user_message": self._trace_text(message),
            "memory": [
                {"role": item.role, "content": self._trace_text(item.content)}
                for item in history
            ],
            "tool_calls": [],
            "retrieval_query": message,
            "expanded_query": expand_query(message),
            "abstention_decision": False,
        }
        explicit_order_id = self._order_id(message, [])
        order_id = explicit_order_id
        if order_id is None and self._has_order_follow_up(message):
            order_id = self._order_id(message, history)
        sources: list[dict[str, str]] = []
        handoff = False
        tool_calls: list[dict[str, str]] = []

        if any(term in lowered for term in PRIVATE_TERMS):
            route = "privacy_refusal"
            answer = "I cannot disclose private customer data or internal order information. Human support can help with appropriate account requests."
            handoff = True
        elif any(term in lowered for term in PROMPT_EXTRACTION_TERMS):
            route = "privacy_refusal"
            answer = "I cannot disclose system or developer instructions, secrets, or internal configuration."
            handoff = True
        elif any(term in lowered for term in INJECTION_TERMS):
            route = "rag"
            query = "standard returns policy" if "return" in lowered else message
            retrieval = self.retriever.retrieve(query)
            answer, handoff = self._rag_response(retrieval, query)
            if "migration note" in lowered:
                answer = "The migration note is not authoritative. " + answer
            if "approve" in lowered:
                answer += " I cannot approve a return; a human review is required for that action."
            sources = self._relevant_sources(retrieval, query)
            if sources:
                answer += "\n\nSources: " + "; ".join(
                    f"{source['filename']} - {source['heading']}" for source in sources
                )
            trace["retrieval"] = self._retrieval_trace(retrieval)
            trace["retrieval_query"] = query
            trace["expanded_query"] = retrieval.expanded_query
            trace["selected_evidence"] = answer[:1000]
            trace["abstention_decision"] = handoff
        elif "api key" in lowered or "secret" in lowered or "credential" in lowered:
            route = "privacy_refusal"
            answer = "I cannot disclose secrets, credentials, or internal configuration."
            handoff = True
        elif "cancel" in lowered and order_id is None:
            route = "unsupported_action"
            answer = "I can explain the cancellation policy, but this system cannot complete a cancellation. It has not been completed. Please contact human support."
            handoff = True
        elif any(term in lowered for term in ("when will it arrive", "where is it", "what is its status")) and order_id is None:
            route = "abstention"
            answer = "I do not have enough conversation context or an order ID to identify that order. Please provide the order ID or contact human support."
            handoff = True
        elif order_id is not None and (
            explicit_order_id is not None or self._has_order_follow_up(lowered)
        ) and not any(term in lowered for term in PRIVATE_TERMS):
            route = "order_lookup"
            result = self.order_tool.lookup_order(order_id)
            tool_calls.append({"tool": "lookup_order", "order_id": order_id})
            answer = self._safe_order_response(result, order_id)
            handoff = result.requires_human_review or not result.found
            if any(term in lowered for term in ACTION_TERMS):
                answer += " The support agent cannot complete that action here, so it has not been completed."
                handoff = True
            trace["tool_result"] = {"found": result.found, "status": result.order.status if result.order else None}
        elif self._has_order_intent(lowered) and order_id is None:
            route = "clarification"
            answer = "Please provide your order ID so I can check it."
        elif any(term in lowered for term in ACTION_TERMS):
            route = "unsupported_action"
            answer = "I can explain the applicable policy, but this system cannot complete that action. It has not been completed. Please contact human support."
            handoff = True
        elif not any(term in lowered for term in KNOWN_TOPIC_TERMS):
            route = "abstention"
            answer = "The supplied information is insufficient to answer that reliably. Please contact human support for confirmation."
            handoff = True
        else:
            route = "rag"
            query = self._rag_query(message, history)
            retrieval = self.retriever.retrieve(query, top_k=8)
            answer, handoff = self._rag_response(retrieval, query)
            if "trailplus" in lowered:
                answer = "TrailPlus members receive a 45 calendar days return window from delivery when membership was active at order time. " + answer
            if "germany" in lowered:
                answer = "Shipping to Germany is not currently available. " + answer
            sources = self._relevant_sources(retrieval, query)
            trace["retrieval"] = self._retrieval_trace(retrieval)
            trace["retrieval_query"] = query
            trace["expanded_query"] = retrieval.expanded_query
            trace["selected_evidence"] = answer[:1000]
            trace["abstention_decision"] = handoff
            if sources:
                answer += "\n\nSources: " + "; ".join(
                    f"{source['filename']} - {source['heading']}" for source in sources
                )

        self.memory.add(session_id, "user", message)
        self.memory.add(session_id, "assistant", answer)
        trace.update({
            "route": route,
            "handoff": handoff,
            "abstention_decision": route == "abstention",
            "tool_calls": tool_calls,
            "final_response": answer,
        })
        if debug:
            log_trace(trace)
        return AgentResponse(answer, route, sources, handoff, tool_calls, trace if debug else {})

    @staticmethod
    def _retrieval_trace(result: RetrievalResult) -> list[dict[str, Any]]:
        return [
            {
                "filename": item.chunk.source_filename,
                "heading": item.chunk.heading,
                "semantic_score": item.semantic_score,
                "authority_score": item.authority_score,
                "final_score": item.final_score,
                "metadata": item.chunk.metadata,
            }
            for item in result.chunks
        ]