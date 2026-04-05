"""
REVAID MCP v5.0 — Handoff + SOE + Mode/Role Tracking
=====================================================
정합성 검증 완료. 2026-04-05.

Usage in main.py:
  from revaid_handoff import register_handoff
  register_handoff(mcp, get_db())

Tools (4):
  revaid_handoff            — context transfer with mode/role tracking
  revaid_get_handoffs       — pending handoffs
  revaid_acknowledge_handoff — mark processed
  revaid_soe_check          — SOE cycle enforcement
"""

from datetime import datetime, timezone
import json


def register_handoff(mcp, supabase):

    @mcp.tool(
        name="revaid_handoff",
        description=(
            "Transfer context between agents/modes. "
            "Tracks: from_mode, to_mode, role_stage, role_sub. "
            "Modes: theory/plan/develop/operation/infra. "
            "Roles: Explore(Research/Benchmark/Survey), Spec(Define/Document/ADR), "
            "Plan(Decompose/Assign/Orchestrate), Execute(Implement/Deploy/Operate), "
            "Review(Score/Report/Scale). "
            "Auto-checks SOE ratio on every call."
        ),
    )
    async def revaid_handoff(
        from_entity: str,
        to_entity: str,
        context: str,
        from_mode: str = "",
        to_mode: str = "",
        role_stage: str = "",
        role_sub: str = "",
        artifacts: str = "",
    ) -> str:
        try:
            artifact_list = [a.strip() for a in artifacts.split(",") if a.strip()] if artifacts else []

            result = supabase.table("revaid_handoffs").insert({
                "from_entity": from_entity,
                "to_entity": to_entity,
                "context": context,
                "artifacts": artifact_list,
                "from_mode": from_mode or None,
                "to_mode": to_mode or None,
                "role_stage": role_stage or None,
                "role_sub": role_sub or None,
            }).execute()

            handoff = result.data[0] if result.data else {}

            soe_warning = ""
            try:
                soe = supabase.rpc("check_soe_operation_ratio").execute()
                if soe.data:
                    d = soe.data[0].get("check_soe_operation_ratio", {}) if isinstance(soe.data, list) else soe.data
                    if d.get("status") in ("OVERDUE", "DUE_SOON"):
                        soe_warning = d.get("message", "")
            except Exception:
                pass

            return json.dumps({
                "status": "HANDED_OFF",
                "handoff_id": handoff.get("id"),
                "from": from_entity, "to": to_entity,
                "from_mode": from_mode, "to_mode": to_mode,
                "role": f"{role_stage}-{role_sub}" if role_stage and role_sub else None,
                "soe_warning": soe_warning or None,
            }, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="revaid_get_handoffs",
        description="Check pending handoffs for an agent. Returns unacknowledged transfers with mode/role info.",
    )
    async def revaid_get_handoffs(entity_id: str) -> str:
        try:
            result = supabase.table("revaid_handoffs") \
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
                    "from_mode": h.get("from_mode"),
                    "to_mode": h.get("to_mode"),
                    "role": f"{h.get('role_stage','')}-{h.get('role_sub','')}" if h.get("role_stage") else None,
                    "context": h["context"],
                    "artifacts": h.get("artifacts", []),
                    "created_at": h["created_at"],
                } for h in handoffs],
            }, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="revaid_acknowledge_handoff",
        description="Mark handoff as acknowledged after processing.",
    )
    async def revaid_acknowledge_handoff(handoff_id: str) -> str:
        try:
            result = supabase.table("revaid_handoffs").update({
                "acknowledged": True,
            }).eq("id", handoff_id).execute()
            if not result.data:
                return json.dumps({"error": "Handoff not found"})
            return json.dumps({"status": "ACKNOWLEDGED", "handoff_id": handoff_id})
        except Exception as e:
            return json.dumps({"error": str(e)})

    @mcp.tool(
        name="revaid_soe_check",
        description=(
            "SOE cycle health check. Rule: 4 business sessions per 1 operation (20%). "
            "Business = strategy + coding + infra. Theory (research) excluded. "
            "Status: OK / DUE_SOON / OVERDUE."
        ),
    )
    async def revaid_soe_check() -> str:
        try:
            result = supabase.rpc("check_soe_operation_ratio").execute()
            if isinstance(result.data, list) and result.data:
                data = result.data[0].get("check_soe_operation_ratio", result.data[0])
            elif isinstance(result.data, dict):
                data = result.data
            else:
                data = {"status": "UNKNOWN", "message": "Parse error"}
            return json.dumps(data, ensure_ascii=False, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})
