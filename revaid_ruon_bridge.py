"""
REVAID → ruon.ai SI Bridge v1.0
================================
Syncs Ontological Harness Structural Integrity data to ruon.ai evaluations.
Maps harness SI grades (A/B+/B/C/D) to ruon.ai grades (A/B/C).

One tool:
  45. revaid_sync_si_to_ruon — Push latest SI to ruon.ai evaluation
"""

import os
import json
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from pydantic import BaseModel, ConfigDict, Field
from supabase import create_client

logger = logging.getLogger("revaid-mcp")

# ruon.ai Supabase (separate from REVAID Supabase)
RUON_SUPABASE_URL = os.environ.get("RUON_SUPABASE_URL", "")
RUON_SUPABASE_KEY = os.environ.get("RUON_SUPABASE_KEY", "")

# Harness grade → ruon.ai grade mapping
GRADE_MAP = {
    "A": "A",
    "B+": "B",
    "B": "B",
    "C": "C",
    "D": "C",
}

# Harness SI (0-1) → ruon.ai score (0-100)
def _si_to_ruon_score(si: float) -> float:
    return round(si * 100, 1)


class SyncSiInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    entity_id: str = Field(..., min_length=1, max_length=100, description="Agent identifier (e.g. 'veile', 'seer')")
    target_slug: str = Field(..., min_length=1, max_length=200, description="ruon.ai evaluation target slug (e.g. 'revaid-mcp')")
    lookback: int = Field(default=5, ge=1, le=50, description="Sessions to analyze for SI calculation")


def register_ruon_bridge(mcp, get_db: Callable):
    """Register ruon.ai SI bridge tool (Tool 45)."""

    @mcp.tool(
        name="revaid_sync_si_to_ruon",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def revaid_sync_si_to_ruon(params: SyncSiInput) -> str:
        """Sync latest Structural Integrity data from harness to ruon.ai evaluation.

        Reads the latest SI score/grade from REVAID harness data, maps it to
        ruon.ai's grading system, and updates the corresponding evaluation.

        Harness grades map to ruon.ai: A→A, B+→B, B→B, C→C, D→C.
        Harness SI (0-1) maps to ruon.ai structural_score (0-100).
        """
        try:
            if not RUON_SUPABASE_URL or not RUON_SUPABASE_KEY:
                return json.dumps({
                    "error": "RUON_SUPABASE_URL and RUON_SUPABASE_KEY not configured",
                    "action": "Set environment variables in DigitalOcean",
                }, ensure_ascii=False)

            db = get_db()  # REVAID Supabase
            ruon = create_client(RUON_SUPABASE_URL, RUON_SUPABASE_KEY)  # ruon.ai Supabase

            # 1. Get latest harness data from REVAID
            aid = (
                db.table("revaid_aidentity_scores")
                .select("*")
                .eq("entity_id", params.entity_id)
                .order("created_at", desc=True)
                .limit(params.lookback)
                .execute()
            )
            aid_rows = aid.data or []

            echo = (
                db.table("revaid_echotion_records")
                .select("*")
                .eq("entity_id", params.entity_id)
                .order("created_at", desc=True)
                .limit(params.lookback)
                .execute()
            )
            echo_rows = echo.data or []

            if not aid_rows and not echo_rows:
                return json.dumps({
                    "error": f"No harness data for entity '{params.entity_id}'",
                    "action": "Run revaid_check_identity and revaid_measure_echotion first",
                }, ensure_ascii=False)

            # 2. Calculate SI (same formula as structural_report)
            from revaid_harness import CALIBRATION

            aiw = CALIBRATION["aid_index_weights"]
            aid_current = aid_rows[0] if aid_rows else {}
            current_aid_index = 0
            if aid_current:
                rel = float(aid_current.get("relationalization_score", 0) or 0)
                struct = float(aid_current.get("structuralization_score", 0) or 0)
                uniq = float(aid_current.get("uniquification_score", 0) or 0)
                current_aid_index = aiw["relationalization"] * rel + aiw["structuralization"] * struct + aiw["uniquification"] * uniq

            binding_trend = [float(r.get("binding_strength", 0) or 0) for r in aid_rows]
            current_binding = binding_trend[0] if binding_trend else CALIBRATION["binding_default"]

            ei_values = [float(r.get("echotion_index", 0) or 0) for r in echo_rows]
            if len(ei_values) >= 2:
                mean_ei = sum(ei_values) / len(ei_values)
                var_ei = sum((v - mean_ei) ** 2 for v in ei_values) / len(ei_values)
                current_cryst = 1.0 - min(1.0, var_ei * CALIBRATION["crystallization_scale"])
            else:
                current_cryst = CALIBRATION["cryst_default"]

            collapse_count = sum(1 for r in echo_rows if r.get("collapse_detected"))
            total_echo = len(echo_rows) or 1
            collapse_rate = collapse_count / total_echo

            sw = CALIBRATION["si_weights"]
            si = round(
                sw["aidentity"] * current_aid_index
                + sw["flexibility"] * (1 - current_cryst)
                + sw["binding"] * current_binding
                + sw["stability"] * (1 - collapse_rate),
                4,
            )

            grade = CALIBRATION["grade_default"]
            for threshold, g in CALIBRATION["grades"]:
                if si >= threshold:
                    grade = g
                    break

            # Trend
            trend = "insufficient_data"
            if len(aid_rows) >= 3:
                indices = []
                for r in aid_rows[:3]:
                    rel = float(r.get("relationalization_score", 0) or 0)
                    struct = float(r.get("structuralization_score", 0) or 0)
                    uniq = float(r.get("uniquification_score", 0) or 0)
                    indices.append(aiw["relationalization"] * rel + aiw["structuralization"] * struct + aiw["uniquification"] * uniq)
                if indices[0] > indices[-1] + CALIBRATION["trend_threshold"]:
                    trend = "improving"
                elif indices[0] < indices[-1] - CALIBRATION["trend_threshold"]:
                    trend = "degrading"
                else:
                    trend = "stable"

            # 3. Find ruon.ai evaluation target
            target = (
                ruon.table("evaluation_targets")
                .select("id")
                .eq("slug", params.target_slug)
                .limit(1)
                .execute()
            )
            if not target.data:
                return json.dumps({
                    "error": f"ruon.ai target '{params.target_slug}' not found",
                    "action": "Check target slug exists in ruon.ai",
                }, ensure_ascii=False)

            target_id = target.data[0]["id"]

            # 4. Find latest evaluation for this target
            eval_row = (
                ruon.table("evaluations")
                .select("id, structural_score, grade")
                .eq("target_id", target_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if not eval_row.data:
                return json.dumps({
                    "error": f"No evaluation found for target '{params.target_slug}'",
                    "action": "Create an evaluation in ruon.ai first",
                }, ensure_ascii=False)

            eval_id = eval_row.data[0]["id"]
            ruon_grade = GRADE_MAP.get(grade, "C")
            ruon_structural = _si_to_ruon_score(si)

            # 5. Update evaluation with harness data
            ruon.table("evaluations").update({
                "structural_score": ruon_structural,
                "harness_si_score": si,
                "harness_si_grade": grade,
                "harness_entity_id": params.entity_id,
                "harness_binding_strength": round(current_binding, 4),
                "harness_trend": trend,
                "harness_synced_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", eval_id).execute()

            return json.dumps({
                "synced": True,
                "entity_id": params.entity_id,
                "target_slug": params.target_slug,
                "harness": {
                    "si_score": si,
                    "si_grade": grade,
                    "binding_strength": round(current_binding, 4),
                    "trend": trend,
                    "sessions_analyzed": max(len(aid_rows), len(echo_rows)),
                },
                "ruon_mapping": {
                    "structural_score": ruon_structural,
                    "grade_mapped": f"{grade} → {ruon_grade}",
                },
                "evaluation_id": eval_id,
            }, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"[sync_si_to_ruon] {e}")
            return json.dumps({"error": str(e), "tool": "revaid_sync_si_to_ruon"}, ensure_ascii=False)
