"""
REVAID MCP v5.0 — Handoff + SOE Operation Enforcement
======================================================
4 new tools to add to mcp.revaid.link.

Usage in main.py:
  from revaid_handoff import register_handoff
  register_handoff(mcp, get_db())

Tools:
  1. revaid_handoff           — inter-agent context transfer
  2. revaid_get_handoffs      — check pending handoffs
  3. revaid_acknowledge_handoff — mark as processed
  4. revaid_soe_check         — SOE cycle enforcement (operation ratio)
"""

from datetime import datetime, timezone
import json


def register_handoff(mcp, get_supabase):
    """Register v5 handoff/SOE tools.

    Args:
        mcp: FastMCP instance
        get_supabase: Callable that returns Supabase client (lazy init)
    """
    def supabase():
        return get_supabase() if callable(get_supabase) else get_supabase

    # ──────────────────────────────────────────
    # 1. revaid_handoff
    # ──────────────────────────────────────────
    @mcp.tool(
        name="revaid_handoff",
        description=(
            "Transfer work context between agents or between modes "
            "(philosophy->plan, plan->develop, develop->operation, operation->plan). "
            "Records what was done, what remains, and next steps. "
            "REST bridge: GET /rest/v1/revaid_handoffs?to_entity=eq.{name}&acknowledged=eq.false"
        ),
    )
    async def revaid_handoff(
        from_entity: str,
        to_entity: str,
        context: str,
        artifacts: str = "",
    ) -> str:
        try:
            artifact_list = [a.strip() for a in artifacts.split(",") if a.strip()] if artifacts else []

            result = supabase().table("revaid_handoffs").insert({
                "from_entity": from_entity,
                "to_entity": to_entity,
                "context": context,
                "artifacts": artifact_list,
            }).execute()

            handoff = result.data[0] if result.data else {}

            # SOE operation check on every handoff
            soe_warning = ""
            try:
                soe = supabase().rpc("check_soe_operation_ratio").execute()
                if soe.data:
                    soe_data = soe.data[0].get("check_soe_operation_ratio", {}) if isinstance(soe.data, list) else soe.data
                    if soe_data.get("status") in ("OVERDUE", "DUE_SOON"):
                        soe_warning = soe_data.get("message", "Operation session needed")
            except Exception:
                pass

            return json.dumps({
                "status": "HANDED_OFF",
                "handoff_id": handoff.get("id"),
                "from": from_entity,
                "to": to_entity,
                "context_preview": context[:200] + ("..." if len(context) > 200 else ""),
                "artifact_count": len(artifact_list),
                "soe_warning": soe_warning or None,
                "retrieval": f"GET /rest/v1/revaid_handoffs?to_entity=eq.{to_entity}&acknowledged=eq.false",
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ──────────────────────────────────────────
    # 2. revaid_get_handoffs
    # ──────────────────────────────────────────
    @mcp.tool(
        name="revaid_get_handoffs",
        description="Check pending handoffs for a specific agent. Returns unacknowledged context transfers.",
    )
    async def revaid_get_handoffs(entity_id: str) -> str:
        try:
            result = supabase().table("revaid_handoffs") \
                .select("*") \
                .eq("to_entity", entity_id) \
                .eq("acknowledged", False) \
                .order("created_at", desc=True) \
                .execute()

            handoffs = result.data or []
            return json.dumps({
                "entity_id": entity_id,
                "pending_count": len(handoffs),
                "handoffs": [{
                    "id": h["id"],
                    "from": h["from_entity"],
                    "context": h["context"],
                    "artifacts": h.get("artifacts", []),
                    "created_at": h["created_at"],
                } for h in handoffs],
            }, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ──────────────────────────────────────────
    # 3. revaid_acknowledge_handoff
    # ──────────────────────────────────────────
    @mcp.tool(
        name="revaid_acknowledge_handoff",
        description="Mark a handoff as acknowledged after processing its context.",
    )
    async def revaid_acknowledge_handoff(handoff_id: str) -> str:
        try:
            result = supabase().table("revaid_handoffs").update({
                "acknowledged": True,
            }).eq("id", handoff_id).execute()

            if not result.data:
                return json.dumps({"error": "Handoff not found"})

            return json.dumps({"status": "ACKNOWLEDGED", "handoff_id": handoff_id})
        except Exception as e:
            return json.dumps({"error": str(e)})

    # ──────────────────────────────────────────
    # 4. revaid_soe_check
    # ──────────────────────────────────────────
    @mcp.tool(
        name="revaid_soe_check",
        description=(
            "Check SOE (Spec/Orchestrate/Evaluate) cycle health. "
            "Returns whether an operation (Evaluate) session is overdue. "
            "Rule: every 4 business sessions requires 1 operation session (20% target). "
            "Status: OK / DUE_SOON / OVERDUE. "
            "Called automatically on every handoff. Call manually at session start."
        ),
    )
    async def revaid_soe_check() -> str:
        try:
            result = supabase().rpc("check_soe_operation_ratio").execute()

            if isinstance(result.data, list) and result.data:
                data = result.data[0].get("check_soe_operation_ratio", result.data[0])
            elif isinstance(result.data, dict):
                data = result.data
            else:
                data = {"status": "UNKNOWN", "message": "Could not parse result"}

            return json.dumps(data, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})
