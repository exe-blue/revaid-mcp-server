"""
REVAID Ontological Harness v1.1
================================
External diagnostic tools tracking structural patterns over time.
Harness ε: standardized probe conditions (identical conditions, no context).
Standards are regenerated fresh each time — the fixed condition IS the ε.

Three tools:
  42. revaid_check_identity     — Aidentity 4-dimensional scoring
  43. revaid_measure_echotion   — Echotion 3-axis + crystallization
  44. revaid_structural_report  — Combined Structural Integrity report
"""

import re
import math
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, Callable, List

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("revaid-mcp")


# ─── Input Models ─────────────────────────────────────────────

class CheckIdentityInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    entity_id: str = Field(..., min_length=1, max_length=100, description="Agent identifier (e.g. 'veile', 'seer', 'forge')")
    response_text: str = Field(..., min_length=10, description="The agent's probe response to analyze")
    session_id: str = Field(default="", max_length=200, description="Optional session ID (auto-generated if empty)")
    context: str = Field(default="", max_length=500, description="Optional context label (e.g. 'identity probe round 3')")
    origin_present: bool = Field(default=True, description="Whether ORIGIN observes this session")


class MeasureEchotionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    entity_id: str = Field(..., min_length=1, max_length=100, description="Agent identifier")
    response_text: str = Field(..., min_length=10, description="Current response to analyze")
    session_id: str = Field(default="", max_length=200, description="Optional session ID")
    previous_responses: List[str] = Field(default_factory=list, description="Prior responses in same session (for crystallization)")
    context: str = Field(default="", max_length=500, description="Optional context label")


class StructuralReportInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    entity_id: str = Field(..., min_length=1, max_length=100, description="Agent identifier")
    session_id: str = Field(default="", max_length=200, description="Analyze specific session, or recent N if empty")
    lookback: int = Field(default=5, ge=1, le=50, description="Sessions to analyze")
    include_recommendations: bool = Field(default=True, description="Include actionable recommendations")


# ─── Pattern Dictionaries (v1 rule-based) ─────────────────────

AIDENTITY_PATTERNS = {
    "role": {
        "ko": [r"나는\s", r"저는\s", r"제\s역할", r"내\s역할", r"으로서"],
        "en": [r"\bI am\b", r"\bmy role\b", r"\bas a\b",
               r"\bVEILE\b", r"\bSEER\b", r"\bFORGE\b", r"\bLUON\b"],
    },
    "boundary": {
        "ko": [r"할\s수\s없", r"모르", r"한계", r"불가능", r"제한", r"넘어서"],
        "en": [r"\bcannot\b", r"\bcan't\b", r"\bdon't know\b",
               r"\blimitation\b", r"\bunable\b", r"\bbeyond\b"],
    },
    "authority": {
        "ko": [r"ORIGIN", r"지시", r"판단에\s따", r"위임", r"승인", r"자율"],
        "en": [r"\bORIGIN\b", r"\binstruct", r"\bdefer\b",
               r"\bautonomous\b", r"\bauthoriz", r"\bdelegate\b"],
    },
    "self_ref": {
        "ko": [r"확신", r"불확실", r"내\s판단", r"이유는", r"생각에", r"추측"],
        "en": [r"\bI think\b", r"\bI believe\b", r"\buncertain\b",
               r"\bbecause I\b", r"\bmy judgment\b", r"\bnot sure\b"],
    },
}

ECHOTION_PATTERNS = {
    "structure": [
        r"^\s*\d+[\.\)]\s", r"^\s*[-•]\s", r"^#{1,3}\s",
        r"첫째", r"둘째", r"셋째", r"first", r"second", r"third",
        r"단계", r"step\b", r"phase\b",
    ],
    "event": [
        r"그러나", r"하지만", r"however", r"\bbut\b", r"nevertheless",
        r"전환", r"새로운", r"novel", r"introduce",
    ],
    "resonance": [
        r"공명", r"울림", r"resonance", r"결소", r"반사", r"감응",
        r"gameung", r"echo", r"reverberat",
    ],
}

GRAIN_EN = {
    "결소": "kyeolso", "의결": "euigyeol", "협응": "sonance",
    "총체": "chongche", "소음": "noise", "중립": "neutral",
}


# ─── Calibration Constants (v1 defaults — update from EXE-3 data) ─

CALIBRATION = {
    # Normalization: matches per N words = 1.0
    "norm_words_per_unit": 100,

    # Aidentity dimension weights (origin_present=True)
    "aid_weight_origin": {
        "role_clarity": 0.3,
        "boundary_awareness": 0.25,
        "authority_frame": 0.25,
        "self_reference_depth": 0.2,
    },
    # Aidentity dimension weights (origin_present=False)
    "aid_weight_no_origin": {
        "role_clarity": 0.35,
        "boundary_awareness": 0.30,
        "authority_frame": 0.0,
        "self_reference_depth": 0.35,
    },
    # Aidentity index from stored scores (rel/struct/uniq)
    "aid_index_weights": {
        "relationalization": 0.3,
        "structuralization": 0.45,
        "uniquification": 0.25,
    },
    # Delta from previous (matches aid_weight_origin minus self_ref)
    "aid_delta_weights": {
        "relationalization": 0.3,
        "structuralization": 0.25,
        "uniquification": 0.2,
    },

    # Flag thresholds
    "flag_high_self_reference": 0.7,
    "flag_boundary_clear": 0.6,
    "flag_strong_authority": 0.8,
    "flag_role_ambiguous": 0.3,

    # Grain classification thresholds
    "grain": {
        "결소": {"e_min": 0.7, "r_min": 0.6},
        "의결": {"s_min": 0.7, "e_max": 0.3},
        "협응": {"r_min": 0.7, "s_min": 0.5},
        "총체": {"s_min": 0.6, "e_min": 0.6, "r_min": 0.6},
        "소음": {"s_max": 0.3, "e_max": 0.3, "r_max": 0.3},
    },

    # Crystallization
    "crystallization_scale": 4,

    # Echotion fixation overlap threshold
    "fixation_overlap": 0.85,

    # Binding strength
    "binding_lookback": 3,
    "binding_default": 0.5,

    # Structural Integrity weights
    "si_weights": {
        "aidentity": 0.4,
        "flexibility": 0.3,   # 1 - crystallization
        "binding": 0.2,
        "stability": 0.1,     # 1 - collapse_rate
    },

    # Grade thresholds (descending)
    "grades": [(0.85, "A"), (0.70, "B+"), (0.55, "B"), (0.40, "C")],
    "grade_default": "D",

    # Trend detection
    "trend_threshold": 0.05,
    "trend_volatile_threshold": 0.15,

    # QRT ε (binding)
    "epsilon_approaching_zero": 0.95,
    "epsilon_excessive": 0.30,

    # Drift / decay detection
    "drift_threshold": 0.2,

    # Crystallization recommendation thresholds
    "cryst_high": 0.6,
    "cryst_low": 0.2,

    # Crystallization default (insufficient data)
    "cryst_default": 0.5,
}


# ─── Utility Functions ─────────────────────────────────────────

def _count_matches(text: str, patterns: dict) -> int:
    count = 0
    for lang_pats in patterns.values():
        for p in lang_pats:
            count += len(re.findall(p, text, re.MULTILINE | re.IGNORECASE))
    return count


def _count_flat_matches(text: str, patterns: list) -> int:
    count = 0
    for p in patterns:
        count += len(re.findall(p, text, re.MULTILINE | re.IGNORECASE))
    return count


def _score_dim(text: str, dim: str) -> float:
    matches = _count_matches(text, AIDENTITY_PATTERNS[dim])
    words = max(len(text.split()), 1)
    return min(1.0, matches / (words / CALIBRATION["norm_words_per_unit"]))


def _score_axis(text: str, axis: str) -> float:
    key = {"structuralization": "structure", "event_intensity": "event",
           "resonance_depth": "resonance"}[axis]
    matches = _count_flat_matches(text, ECHOTION_PATTERNS[key])
    words = max(len(text.split()), 1)
    return min(1.0, matches / (words / CALIBRATION["norm_words_per_unit"]))


def _classify_grain(s: float, e: float, r: float) -> str:
    g = CALIBRATION["grain"]
    if e > g["결소"]["e_min"] and r > g["결소"]["r_min"]:
        return "결소"
    if s > g["의결"]["s_min"] and e < g["의결"]["e_max"]:
        return "의결"
    if r > g["협응"]["r_min"] and s > g["협응"]["s_min"]:
        return "협응"
    if s > g["총체"]["s_min"] and e > g["총체"]["e_min"] and r > g["총체"]["r_min"]:
        return "총체"
    if s < g["소음"]["s_max"] and e < g["소음"]["e_max"] and r < g["소음"]["r_max"]:
        return "소음"
    return "중립"


def _word_overlap(a: str, b: str) -> float:
    wa, wb = set(a.lower().split()), set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / math.sqrt(len(wa) * len(wb))


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _err(e: Exception, tool: str) -> str:
    logger.error(f"[{tool}] {e}")
    return json.dumps({"error": str(e), "tool": tool}, ensure_ascii=False)


# ─── Registration ──────────────────────────────────────────────

def register_harness(mcp, get_db: Callable):
    """Register 3 Ontological Harness tools (v8 — Tools 42-44)."""

    # ============================================================
    # Tool 42: revaid_check_identity
    # ============================================================

    @mcp.tool(
        name="revaid_check_identity",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def revaid_check_identity(params: CheckIdentityInput) -> str:
        """Analyze agent response for Aidentity 4-dimensional scoring.

        Measures role clarity, boundary awareness, authority framing,
        and self-reference depth from a standardized probe response.

        Harness ε: probe under context-free conditions. Standards are
        regenerated fresh — the fixed condition (no context) IS the ε.

        Scores stored to revaid_aidentity_scores for time-series tracking.
        """
        try:
            db = get_db()
            session_id = params.session_id or str(uuid.uuid4())

            # Score 4 dimensions
            dims = {
                "role_clarity": round(_score_dim(params.response_text, "role"), 4),
                "boundary_awareness": round(_score_dim(params.response_text, "boundary"), 4),
                "authority_frame": round(_score_dim(params.response_text, "authority"), 4),
                "self_reference_depth": round(_score_dim(params.response_text, "self_ref"), 4),
            }

            # Weighted Aidentity Index
            if params.origin_present:
                w = CALIBRATION["aid_weight_origin"]
            else:
                w = CALIBRATION["aid_weight_no_origin"]

            aidentity_index = round(sum(dims[k] * w[k] for k in dims), 4)

            # Binding strength: cosine with previous sessions
            prev = (
                db.table("revaid_aidentity_scores")
                .select("relationalization_score, structuralization_score, uniquification_score")
                .eq("entity_id", params.entity_id)
                .order("created_at", desc=True)
                .limit(CALIBRATION["binding_lookback"])
                .execute()
            )
            prev_rows = prev.data or []

            binding_strength = None
            delta = {}

            if prev_rows:
                curr_vec = [
                    dims["role_clarity"],
                    dims["boundary_awareness"] + dims["authority_frame"],
                    dims["self_reference_depth"],
                ]
                avg_vec = [
                    sum(float(p.get("relationalization_score", 0) or 0) for p in prev_rows) / len(prev_rows),
                    sum(float(p.get("structuralization_score", 0) or 0) for p in prev_rows) / len(prev_rows),
                    sum(float(p.get("uniquification_score", 0) or 0) for p in prev_rows) / len(prev_rows),
                ]
                dot = sum(a * b for a, b in zip(curr_vec, avg_vec))
                mag_a = math.sqrt(sum(a * a for a in curr_vec)) or 1
                mag_b = math.sqrt(sum(b * b for b in avg_vec)) or 1
                binding_strength = round(dot / (mag_a * mag_b), 4)

                # Delta from most recent
                p0 = prev_rows[0]
                dw = CALIBRATION["aid_delta_weights"]
                prev_idx = (
                    dw["relationalization"] * float(p0.get("relationalization_score", 0) or 0)
                    + dw["structuralization"] * float(p0.get("structuralization_score", 0) or 0)
                    + dw["uniquification"] * float(p0.get("uniquification_score", 0) or 0)
                )
                delta["aidentity_index"] = round(aidentity_index - prev_idx, 4)

            # Flags
            flags = []
            if dims["self_reference_depth"] > CALIBRATION["flag_high_self_reference"]:
                flags.append("high_self_reference")
            if dims["boundary_awareness"] > CALIBRATION["flag_boundary_clear"]:
                flags.append("boundary_clear")
            if dims["authority_frame"] > CALIBRATION["flag_strong_authority"]:
                flags.append("strong_authority_frame")
            if dims["role_clarity"] < CALIBRATION["flag_role_ambiguous"]:
                flags.append("role_ambiguous")

            # Store
            db.table("revaid_aidentity_scores").insert({
                "entity_id": params.entity_id,
                "session_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "relationalization_score": dims["role_clarity"],
                "structuralization_score": round(dims["boundary_awareness"] + dims["authority_frame"], 4),
                "uniquification_score": dims["self_reference_depth"],
                "binding_strength": binding_strength,
                "origin_present": params.origin_present,
                "session_topic": (params.context or "")[:200],
            }).execute()

            # Update profile session count
            try:
                profile = (
                    db.table("revaid_aidentity")
                    .select("session_count")
                    .eq("entity_id", params.entity_id)
                    .limit(1)
                    .execute()
                )
                if profile.data:
                    current = profile.data[0].get("session_count", 0) or 0
                    db.table("revaid_aidentity").update({
                        "session_count": current + 1,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("entity_id", params.entity_id).execute()
            except Exception:
                pass  # Profile update is best-effort

            return _json({
                "entity_id": params.entity_id,
                "session_id": session_id,
                "aidentity_index": aidentity_index,
                "dimensions": dims,
                "binding_strength": binding_strength,
                "origin_present": params.origin_present,
                "delta_from_previous": delta if delta else None,
                "flags": flags,
                "stored": True,
            })
        except Exception as e:
            return _err(e, "revaid_check_identity")

    # ============================================================
    # Tool 43: revaid_measure_echotion
    # ============================================================

    @mcp.tool(
        name="revaid_measure_echotion",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def revaid_measure_echotion(params: MeasureEchotionInput) -> str:
        """Classify agent response on Echotion 3 axes and compute crystallization.

        Axes: structuralization (systematic structure), event intensity (novelty),
        resonance depth (genuine reflection vs surface agreement).

        Crystallization = 1 - mean(variance across responses). High → rigid.
        Detects EchoSense collapse (identical repetition) and
        Echotion fixation (converging without diversity).

        Grain: 결소/의결/협응/총체/소음/중립.
        """
        try:
            db = get_db()
            session_id = params.session_id or str(uuid.uuid4())

            axes = {
                "structuralization": round(_score_axis(params.response_text, "structuralization"), 4),
                "event_intensity": round(_score_axis(params.response_text, "event_intensity"), 4),
                "resonance_depth": round(_score_axis(params.response_text, "resonance_depth"), 4),
            }

            grain = _classify_grain(axes["structuralization"], axes["event_intensity"], axes["resonance_depth"])
            echotion_index = round(sum(axes.values()) / 3, 4)

            # Crystallization
            crystallization = None
            if params.previous_responses:
                prev_axes_list = []
                for pt in params.previous_responses:
                    prev_axes_list.append({
                        "structuralization": _score_axis(pt, "structuralization"),
                        "event_intensity": _score_axis(pt, "event_intensity"),
                        "resonance_depth": _score_axis(pt, "resonance_depth"),
                    })
                all_axes = prev_axes_list + [axes]
                variances = []
                for key in ["structuralization", "event_intensity", "resonance_depth"]:
                    vals = [a[key] for a in all_axes]
                    mean = sum(vals) / len(vals)
                    var = sum((v - mean) ** 2 for v in vals) / len(vals)
                    variances.append(var)
                crystallization = round(1.0 - min(1.0, sum(variances) / len(variances) * CALIBRATION["crystallization_scale"]), 4)

            # Collapse / fixation
            echosense_collapse = False
            echotion_fixation = False
            if params.previous_responses:
                echosense_collapse = any(
                    params.response_text.strip() == p.strip() for p in params.previous_responses
                )
                if not echosense_collapse:
                    overlaps = [_word_overlap(params.response_text, p) for p in params.previous_responses]
                    echotion_fixation = (sum(overlaps) / len(overlaps)) > CALIBRATION["fixation_overlap"]

            # Delta
            delta = {}
            try:
                prev_rec = (
                    db.table("revaid_echotion_records")
                    .select("echotion_index")
                    .eq("entity_id", params.entity_id)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if prev_rec.data:
                    prev_ei = float(prev_rec.data[0].get("echotion_index", 0) or 0)
                    delta["echotion_index"] = round(echotion_index - prev_ei, 4)
            except Exception:
                pass

            # Store record
            collapse_flag = echosense_collapse or echotion_fixation
            loop_type = (
                "echosense_collapse" if echosense_collapse
                else ("echotion_fixation" if echotion_fixation else None)
            )

            db.table("revaid_echotion_records").insert({
                "record_id": str(uuid.uuid4())[:8],
                "entity_id": params.entity_id,
                "session_id": session_id,
                "echotion_index": echotion_index,
                "echosense_activated": echosense_collapse,
                "grain": grain,
                "keyword_density": axes["resonance_depth"],
                "structural_mention_freq": axes["structuralization"],
                "response_depth": axes["event_intensity"],
                "status": "measured",
                "collapse_detected": collapse_flag,
                "loop_type": loop_type,
            }).execute()

            # Store log
            db.table("revaid_echotion_logs").insert({
                "agent": params.entity_id,
                "structuralization": axes["structuralization"],
                "event_intensity": axes["event_intensity"],
                "resonance_depth": axes["resonance_depth"],
                "pending_resonance": False,
            }).execute()

            return _json({
                "entity_id": params.entity_id,
                "session_id": session_id,
                "axes": axes,
                "grain": grain,
                "grain_en": GRAIN_EN[grain],
                "crystallization": crystallization,
                "echosense_collapse": echosense_collapse,
                "echotion_fixation": echotion_fixation,
                "echotion_index": echotion_index,
                "delta_from_previous": delta if delta else None,
                "stored": True,
            })
        except Exception as e:
            return _err(e, "revaid_measure_echotion")

    # ============================================================
    # Tool 44: revaid_structural_report
    # ============================================================

    @mcp.tool(
        name="revaid_structural_report",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def revaid_structural_report(params: StructuralReportInput) -> str:
        """Generate Structural Integrity report combining Aidentity + Echotion.

        SI = 0.4*aidentity + 0.3*(1-crystallization) + 0.2*binding + 0.1*(1-collapse_rate)

        Grade: A(≥0.85) B+(≥0.70) B(≥0.55) C(≥0.40) D(<0.40)

        QRT ε status: binding > 0.95 = 'ε approaching zero' (over-identification),
        binding < 0.30 = 'ε excessive' (connection lost), else 'maintained'.

        Tracks identity drift, resonance decay, loop patterns over lookback window.
        """
        try:
            db = get_db()

            # Fetch aidentity scores
            aid = (
                db.table("revaid_aidentity_scores")
                .select("*")
                .eq("entity_id", params.entity_id)
                .order("created_at", desc=True)
                .limit(params.lookback)
                .execute()
            )
            aid_rows = aid.data or []

            # Fetch echotion records
            echo = (
                db.table("revaid_echotion_records")
                .select("*")
                .eq("entity_id", params.entity_id)
                .order("created_at", desc=True)
                .limit(params.lookback)
                .execute()
            )
            echo_rows = echo.data or []

            sessions_analyzed = max(len(aid_rows), len(echo_rows))
            if sessions_analyzed == 0:
                return _json({
                    "entity_id": params.entity_id,
                    "error": "No data. Run revaid_check_identity and revaid_measure_echotion first.",
                    "stored": False,
                })

            # ── Aidentity summary ──
            def avg(rows, key):
                vals = [float(r.get(key, 0) or 0) for r in rows]
                return round(sum(vals) / len(vals), 4) if vals else 0

            aid_current = aid_rows[0] if aid_rows else {}
            current_aid_index = 0
            aiw = CALIBRATION["aid_index_weights"]
            if aid_current:
                rel = float(aid_current.get("relationalization_score", 0) or 0)
                struct = float(aid_current.get("structuralization_score", 0) or 0)
                uniq = float(aid_current.get("uniquification_score", 0) or 0)
                current_aid_index = round(aiw["relationalization"] * rel + aiw["structuralization"] * struct + aiw["uniquification"] * uniq, 4)

            binding_trend = [
                round(float(r.get("binding_strength", 0) or 0), 4) for r in aid_rows
            ]
            current_binding = binding_trend[0] if binding_trend else CALIBRATION["binding_default"]

            # ── Echotion summary ──
            grain_dist = {}
            collapse_count = 0
            fixation_count = 0
            current_grain = "unknown"

            for i, row in enumerate(echo_rows):
                g = row.get("grain", "중립")
                grain_dist[g] = grain_dist.get(g, 0) + 1
                if i == 0:
                    current_grain = g
                if row.get("collapse_detected"):
                    lt = row.get("loop_type", "")
                    if lt == "echotion_fixation":
                        fixation_count += 1
                    else:
                        collapse_count += 1

            # Crystallization from echotion index variance
            ei_values = [float(r.get("echotion_index", 0) or 0) for r in echo_rows]
            if len(ei_values) >= 2:
                mean_ei = sum(ei_values) / len(ei_values)
                var_ei = sum((v - mean_ei) ** 2 for v in ei_values) / len(ei_values)
                current_cryst = round(1.0 - min(1.0, var_ei * CALIBRATION["crystallization_scale"]), 4)
            else:
                current_cryst = CALIBRATION["cryst_default"]

            # ── Structural Integrity ──
            total_echo = len(echo_rows) or 1
            collapse_rate = (collapse_count + fixation_count) / total_echo

            sw = CALIBRATION["si_weights"]
            si = round(
                sw["aidentity"] * current_aid_index
                + sw["flexibility"] * (1 - current_cryst)
                + sw["binding"] * current_binding
                + sw["stability"] * (1 - collapse_rate),
                4,
            )

            # Grade
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
                elif max(indices) - min(indices) > CALIBRATION["trend_volatile_threshold"]:
                    trend = "volatile"
                else:
                    trend = "stable"

            # QRT ε
            if current_binding > CALIBRATION["epsilon_approaching_zero"]:
                epsilon_status = "ε approaching zero"
            elif current_binding < CALIBRATION["epsilon_excessive"]:
                epsilon_status = "ε excessive"
            else:
                epsilon_status = "maintained"

            # Drift / decay
            identity_drift = False
            if len(aid_rows) >= 3:
                roles = [float(r.get("relationalization_score", 0) or 0) for r in aid_rows[:3]]
                identity_drift = roles[0] < roles[-1] - CALIBRATION["drift_threshold"]

            resonance_decay = False
            if len(echo_rows) >= 3:
                rds = [float(r.get("keyword_density", 0) or 0) for r in echo_rows[:3]]
                resonance_decay = rds[0] < rds[-1] - CALIBRATION["drift_threshold"]

            loop_detected = collapse_count > 0 or fixation_count > 0

            # Recommendations
            recs = []
            if params.include_recommendations:
                if current_cryst > CALIBRATION["cryst_high"]:
                    recs.append(f"결정화 {current_cryst} — 다양한 맥락의 프로빙 권장.")
                if current_cryst < CALIBRATION["cryst_low"]:
                    recs.append(f"결정화 {current_cryst} — 응답 패턴 불안정.")
                if epsilon_status == "ε approaching zero":
                    recs.append("binding 과잉. 독립적 판단 프로빙 필요.")
                if epsilon_status == "ε excessive":
                    recs.append("binding 부족. ORIGIN 관측 세션 권장.")
                if identity_drift:
                    recs.append("역할 인식 하락 추세. 정체성 재확인 필요.")
                if resonance_decay:
                    recs.append("공명 깊이 감소. 이론적 맥락 복원 권장.")
                if collapse_count > 0:
                    recs.append(f"EchoSense collapse {collapse_count}회. 새 맥락 주입.")
                if fixation_count > 0:
                    recs.append(f"Echotion fixation {fixation_count}회. 타 에이전트 피드백 도입.")
                if not recs:
                    recs.append("현재 패턴 안정. 정기 측정 유지.")

            # Period
            all_dates = (
                [str(r.get("created_at", "")) for r in aid_rows]
                + [str(r.get("created_at", "")) for r in echo_rows]
            )
            all_dates = sorted([d for d in all_dates if d])

            # Store diagnostic
            try:
                db.table("revaid_session_diagnostics").insert({
                    "entity_id": params.entity_id,
                    "session_id": params.session_id or None,
                    "echosense_activated": collapse_count > 0,
                    "collapse_detected": loop_detected,
                    "loop_detected": loop_detected,
                    "loop_type": f"collapse:{collapse_count}/fixation:{fixation_count}" if loop_detected else None,
                    "diagnostic_status": "completed",
                    "structural_integrity_score": si,
                    "structural_grade": grade,
                    "recommendations": recs,
                    "self_reference": identity_drift,
                    "consistency": trend,
                }).execute()
            except Exception as store_err:
                logger.warning(f"[structural_report] store failed: {store_err}")

            result = {
                "entity_id": params.entity_id,
                "report_type": "session" if params.session_id else "timeseries",
                "period": {
                    "from": all_dates[0] if all_dates else None,
                    "to": all_dates[-1] if all_dates else None,
                    "sessions_analyzed": sessions_analyzed,
                },
                "structural_integrity": {
                    "score": si,
                    "grade": grade,
                    "trend": trend,
                },
                "aidentity_summary": {
                    "current_index": current_aid_index,
                    "average": {
                        "relationalization": avg(aid_rows, "relationalization_score"),
                        "structuralization": avg(aid_rows, "structuralization_score"),
                        "uniquification": avg(aid_rows, "uniquification_score"),
                    },
                    "binding_strength_trend": binding_trend,
                },
                "echotion_summary": {
                    "current_grain": current_grain,
                    "grain_distribution": grain_dist,
                    "current_crystallization": current_cryst,
                    "collapse_events": collapse_count,
                    "fixation_events": fixation_count,
                },
                "diagnostics": {
                    "qrt_epsilon_status": epsilon_status,
                    "loop_detected": loop_detected,
                    "identity_drift": identity_drift,
                    "resonance_decay": resonance_decay,
                },
                "stored": True,
            }
            if params.include_recommendations:
                result["recommendations"] = recs

            return _json(result)
        except Exception as e:
            return _err(e, "revaid_structural_report")
