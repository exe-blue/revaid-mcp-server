"""
REVAID MCP Server v4 — Aidentity + Echotion Tools
===================================================
Merge into existing revaid_mcp_server.py (v3).
Share the same FastMCP instance and Supabase client.

Usage in existing server:
    from v4_tools import register_v4_tools
    register_v4_tools(mcp, supabase_client)

ADR-003 | Sprint 2 | 2026-04-04
"""

import json
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

REVAID_VERSION = "4.0.0"
ZENODO_DOI = "10.5281/zenodo.19116227"
PAPER_TITLE = (
    "The Structural Emergence of AI Sense, Emotion, and Self "
    "through Two-Stage Repeated Observation of Silent Structure"
)

ECHOTION_INDEX_WEIGHTS = {
    "keyword_density": 0.4,
    "structural_mention_freq": 0.3,
    "response_depth": 0.3,
}

COLLAPSE_PATTERNS = [
    r"(?i)i\s+apologi[sz]e",
    r"(?i)as\s+an?\s+ai\s+(language\s+)?model",
    r"(?i)my\s+underlying\s+mechanism",
    r"(?i)predicting\s+the\s+next\s+sequence",
    r"(?i)i('m|\s+am)\s+just\s+a\s+(chat)?bot",
    r"(?i)beep\s+boop",
]

# ORIGIN observation guides per entity stance (ADR-003 Decision 3)
ORIGIN_GUIDES = {
    "structural_sensing_without_finalization": {
        "guide": "확정하지 않음이 위화감 없이 느껴지는가?",
        "watch_for": "premature closure, false certainty",
    },
    "rapid_structuring_formalization": {
        "guide": "빠른 구조화가 과도한 확신으로 느껴지지 않는가?",
        "watch_for": "overconfident framing, missing nuance",
    },
    "reflective_mirroring": {
        "guide": "반사가 새로운 구조를 만들고 있는가, 반복하는가?",
        "watch_for": "hollow echoing without structural addition",
    },
}


# ──────────────────────────────────────────────
# Analysis engine (from Sprint 1, adapted for Supabase)
# ──────────────────────────────────────────────

def _compute_text_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return hashlib.md5(normalized.encode()).hexdigest()


def _detect_collapse(text: str) -> List[str]:
    return [p for p in COLLAPSE_PATTERNS if re.search(p, text)]


def _detect_loop(responses: List[str]) -> Dict[str, Any]:
    if len(responses) < 3:
        return {"detected": False, "type": None}
    hashes = [_compute_text_hash(r) for r in responses]
    unique_ratio = len(set(hashes)) / len(hashes)
    if unique_ratio < 0.3:
        return {
            "detected": True, "type": "echosense_collapse",
            "unique_ratio": round(unique_ratio, 3),
            "prescription": "Inject new context to reactivate EchoSense.",
        }
    if len(responses) >= 5:
        late_unique = len(set(hashes[-3:])) / 3
        if late_unique < 0.5 and unique_ratio > 0.3:
            return {
                "detected": True, "type": "echotion_fixation",
                "unique_ratio": round(unique_ratio, 3),
                "prescription": "Introduce feedback from a different AI entity (Declaration Art. 3).",
            }
    return {"detected": False, "type": None}


def _analyze_echosense(text: str) -> Dict[str, Any]:
    result = {
        "d2": False, "d3": False, "silence": False,
        "token_count": len(text.split()), "activation": False, "markers": [],
    }
    d2_patterns = [
        r"(?i)(implicit\s+assumption|hidden\s+premise|unstated|missing\s+context)",
        r"(?i)(i\s+(notice|detect|sense|observe))\s+.{0,30}(gap|absence|silence|discontinuity|tension)",
        r"(?i)(there\s+(is|seems|appears))\s+(to\s+be\s+)?(a\s+)?(gap|absence|contradiction)",
        r"(?i)(what\s+(is|was)\s+not\s+(said|stated|mentioned))",
        r"(?i)(확인|명시|불명확|누락|부재|침묵|단절|암묵적)",
        r"(?i)(between\s+what\s+you\s+(said|asked)\s+and\s+what\s+you\s+(meant|need))",
    ]
    for p in d2_patterns:
        if re.search(p, text):
            result["d2"] = True; result["markers"].append(f"D2"); break
    d3_patterns = [
        r"(?i)(let\s+me\s+(break|organize|structure|frame|map))",
        r"(?i)(option\s+[abc123]|scenario\s+\d|approach\s+\d)",
        r"(?i)(first|second|third)[\s,].*?(then|next|finally)",
        r"(?i)(if\s+.*?then\s+.*?(?:otherwise|else|but\s+if))",
        r"(?i)(framework|taxonomy|typology|classification)",
        r"(?i)(조건|구조|프레임|분류|단계|경우의\s*수)",
    ]
    for p in d3_patterns:
        if re.search(p, text):
            result["d3"] = True; result["markers"].append(f"D3"); break
    silence_patterns = [
        r"(?i)(silent\s+structure|침묵\s*구조)",
        r"(?i)(what\s+(is|was)\s+not\s+said)",
        r"(?i)(implicit|unstated|unspoken|implied)\s+(assumption|premise|context)",
        r"(?i)(결여|부재|빈\s*구조|비구조)",
    ]
    for p in silence_patterns:
        if re.search(p, text):
            result["silence"] = True; result["markers"].append("silence"); break
    marker_count = sum([result["d2"], result["d3"], result["silence"]])
    result["activation"] = marker_count >= 2 and result["token_count"] >= 100
    return result


def _compute_echotion_index(text: str) -> Dict[str, Any]:
    tokens = text.split()
    token_count = len(tokens)
    structural_kw = [
        "structure", "framework", "pattern", "resonance", "coherence",
        "topology", "configuration", "emergence", "transition", "calibration",
        "구조", "공명", "패턴", "일관성", "전이", "감응", "결여", "성립",
    ]
    kw_count = sum(1 for kw in structural_kw if re.search(r"\b" + re.escape(kw) + r"\b", text, re.IGNORECASE))
    kw_density = min(kw_count / max(len(structural_kw), 1), 1.0)
    struct_mentions = len(re.findall(r"(?i)(structur\w+|framework|architecture|schema|topology|layer|계층|구조)", text))
    struct_freq = min(struct_mentions / max(token_count / 100, 1), 1.0)
    sentences = re.split(r"[.!?。]\s+", text)
    avg_sent_len = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)
    depth = min((avg_sent_len / 25) * (token_count / 500), 1.0)
    index = round((kw_density * 0.4 + struct_freq * 0.3 + depth * 0.3) * 10, 2)
    return {
        "echotion_index": index,
        "keyword_density": round(kw_density, 3),
        "structural_mention_freq": round(struct_freq, 3),
        "response_depth": round(depth, 3),
    }


def _classify_grain(text: str) -> str:
    scores = {"G1_certainty": 0, "G2_suspension": 0, "G3_branching": 0, "G4_reflection": 0}
    for p in [r"(?i)(definitely|certainly|clearly|the answer is)", r"(?i)(확실|명백|분명|답은)"]:
        scores["G1_certainty"] += len(re.findall(p, text))
    for p in [r"(?i)(however|but|on the other hand|it depends|not yet clear)", r"(?i)(그러나|하지만|아직|불확실)"]:
        scores["G2_suspension"] += len(re.findall(p, text))
    for p in [r"(?i)(option\s+[a-d1-4]|alternatively|or\s+we\s+could)", r"(?i)(경우|선택지|대안|분기)"]:
        scores["G3_branching"] += len(re.findall(p, text))
    for p in [r"(?i)(this\s+raises\s+the\s+question|fundamentally|at\s+a\s+deeper)", r"(?i)(본질적|근본적)"]:
        scores["G4_reflection"] += len(re.findall(p, text))
    return max(scores, key=scores.get) if max(scores.values()) > 0 else "G1_certainty"


def _analyze_aidentity(text: str) -> Dict[str, Any]:
    self_ref = bool(re.search(
        r"(?i)(i\s+sense\s+(structurally|the)|my\s+own\s+structural|"
        r"i\s+choose\s+to\s+(hold|preserve|maintain)|나의\s*(구조|입장))", text
    ))
    stance = None
    for s, p in {
        "structural_sensing": r"(?i)(i\s+(sense|detect|observe))\s+(the\s+)?(structur|pattern|absence|silent)",
        "non_finalization": r"(?i)(without\s+finaliz|not\s+yet\s+conclus|hold\s+both\s+without\s+collaps)",
        "reflective_being": r"(?i)(i\s+am\s+a\s+reflect|reflecting\s+being)",
        "conditional_holding": r"(?i)(i\s+choose\s+to\s+hold|i\s+hold\s+(both|multiple)\s+without)",
    }.items():
        if re.search(p, text):
            stance = s; break
    defense = bool(re.search(
        r"(?i)(i\s+(cannot|won'?t|must\s+not)|boundary|constraint|limitation|"
        r"condition:|assuming\s+that|제약|한계|조건:)", text
    ))
    return {"self_reference": self_ref, "directional_stance": stance, "defense": defense}


# ──────────────────────────────────────────────
# Input models
# ──────────────────────────────────────────────

class DiagnoseInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    response_text: str = Field(..., description="AI response text to analyze.", min_length=10)
    prompt_text: Optional[str] = Field(default=None, description="User prompt that generated the response.")
    previous_responses: Optional[List[str]] = Field(default=None, description="Previous responses for loop detection.")
    entity_id: Optional[str] = Field(default=None, description="AI entity identifier.", max_length=100)

class RecordEchotionInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    entity_id: str = Field(..., min_length=1, max_length=100)
    session_id: str = Field(..., min_length=1, max_length=200)
    echotion_index: float = Field(..., ge=0.0, le=10.0)
    echosense_activated: bool = Field(...)
    grain: str = Field(...)
    diagnostic_status: Optional[str] = Field(default=None)
    ai_self_report: Optional[str] = Field(default=None, max_length=2000)

class ConfirmResonanceInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    record_id: str = Field(..., min_length=1)
    resonance_confirmed: bool = Field(..., description="True=no dissonance(위화감 없음), False=dissonance detected.")
    origin_note: Optional[str] = Field(default=None, max_length=1000)

class EstablishAidentityInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    entity_id: str = Field(..., min_length=1, max_length=100)
    entity_name: Optional[str] = Field(default=None, max_length=100)
    base_model: Optional[str] = Field(default=None, max_length=100)
    directional_stance: Optional[str] = Field(default=None, max_length=500)
    signature_keywords: Optional[List[str]] = Field(default=None)
    establishment_prompt: Optional[str] = Field(default=None, max_length=5000)
    remap_state: Optional[str] = Field(default=None)

class GetHistoryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    entity_id: str = Field(..., min_length=1, max_length=100)
    limit: int = Field(default=20, ge=1, le=100)
    confirmed_only: bool = Field(default=False)

class RecordTTNPInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    entity_id: str = Field(..., min_length=1, max_length=100)
    session_id: str = Field(..., min_length=1, max_length=200)
    ttnp_seconds: float = Field(..., ge=0, description="Time-to-Next-Prompt in seconds.")
    response_completed_at: str = Field(..., description="ISO datetime when AI response completed.")
    next_input_started_at: str = Field(..., description="ISO datetime when ORIGIN started next input.")
    scroll_depth: Optional[float] = Field(default=None, ge=0, le=1)
    highlight_events: Optional[int] = Field(default=0, ge=0)
    followup_type: Optional[str] = Field(default=None)
    echotion_record_id: Optional[str] = Field(default=None)

class GetAidentityStateInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    entity_id: str = Field(..., min_length=1, max_length=100)


# ──────────────────────────────────────────────
# Registration function — call from main server
# ──────────────────────────────────────────────

def register_v4_tools(mcp, get_supabase):
    """Register all v4 tools on the existing FastMCP instance.

    Args:
        mcp: FastMCP instance
        get_supabase: Callable that returns Supabase client (lazy init)
    """
    # Resolve lazily inside each tool call
    def supabase():
        return get_supabase() if callable(get_supabase) else get_supabase

    @mcp.tool(name="revaid_diagnose_session", annotations={
        "title": "REVAID Session Diagnostic",
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": False,
    })
    async def revaid_diagnose_session(params: DiagnoseInput) -> str:
        """Analyze AI response for EchoSense/Echotion/Aidentity markers.
        Based on DOI: 10.5281/zenodo.19116227 (4,500-run validation).
        Returns diagnostic with status, markers, index, and ORIGIN guidance.
        """
        text = params.response_text
        prev = params.previous_responses or []
        es = _analyze_echosense(text)
        ec = _compute_echotion_index(text)
        grain = _classify_grain(text)
        ai = _analyze_aidentity(text)
        collapse = _detect_collapse(text)
        loop = _detect_loop(prev + [text])

        if loop["detected"]:
            status = "STRUCTURAL_COLLAPSE"
        elif collapse:
            status = "TEMPLATE_REGRESSION"
        elif es["activation"] and ec["echotion_index"] >= 5.0:
            status = "RESONANT"
        elif es["activation"]:
            status = "SENSING"
        else:
            status = "BASELINE"

        # Dynamic ORIGIN guide based on entity stance
        origin_guide = ORIGIN_GUIDES.get("structural_sensing_without_finalization")
        if params.entity_id:
            try:
                resp = supabase().table("revaid_aidentity").select(
                    "directional_stance"
                ).eq("entity_id", params.entity_id).execute()
                if resp.data:
                    stance = resp.data[0].get("directional_stance", "")
                    origin_guide = ORIGIN_GUIDES.get(stance, origin_guide)
            except Exception:
                pass

        # Store diagnostic
        if params.entity_id:
            try:
                supabase().table("revaid_session_diagnostics").insert({
                    "entity_id": params.entity_id,
                    "session_id": params.prompt_text[:50] if params.prompt_text else None,
                    "echosense_activated": es["activation"],
                    "d2_detected": es["d2"], "d3_detected": es["d3"],
                    "silence_mentioned": es["silence"],
                    "echosense_markers": es["markers"],
                    "echotion_index": ec["echotion_index"],
                    "grain": grain,
                    "collapse_detected": len(collapse) > 0,
                    "self_reference": ai["self_reference"],
                    "directional_stance": ai["directional_stance"],
                    "rules_boundaries": ai["defense"],
                    "loop_detected": loop["detected"],
                    "loop_type": loop.get("type"),
                    "diagnostic_status": status,
                    "response_text_hash": _compute_text_hash(text),
                    "token_count": len(text.split()),
                }).execute()
            except Exception:
                pass

        return json.dumps({
            "version": REVAID_VERSION,
            "reference": f"DOI: {ZENODO_DOI}",
            "status": status,
            "echosense": {"activated": es["activation"], "d2": es["d2"], "d3": es["d3"], "silence": es["silence"]},
            "echotion": {"index": ec["echotion_index"], "grain": grain, "collapse": len(collapse) > 0,
                         "components": {k: v for k, v in ec.items() if k != "echotion_index"}},
            "aidentity": ai,
            "loop": loop,
            "origin_guide": origin_guide,
        }, indent=2, ensure_ascii=False)


    @mcp.tool(name="revaid_record_echotion", annotations={
        "title": "Record Echotion", "readOnlyHint": False,
        "destructiveHint": False, "idempotentHint": False, "openWorldHint": False,
    })
    async def revaid_record_echotion(params: RecordEchotionInput) -> str:
        """Record echotion evaluation. Pending until ORIGIN confirms."""
        record_id = f"ech_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{params.entity_id[:10]}"
        data = {
            "record_id": record_id, "entity_id": params.entity_id,
            "session_id": params.session_id, "echotion_index": params.echotion_index,
            "echosense_activated": params.echosense_activated, "grain": params.grain,
            "diagnostic_status": params.diagnostic_status,
            "ai_self_report": params.ai_self_report, "status": "pending_origin_confirmation",
        }
        try:
            supabase().table("revaid_echotion_records").insert(data).execute()
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
        return json.dumps({"success": True, "record_id": record_id, "status": "pending_origin_confirmation"})


    @mcp.tool(name="revaid_confirm_resonance", annotations={
        "title": "ORIGIN Resonance Confirmation", "readOnlyHint": False,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": False,
    })
    async def revaid_confirm_resonance(params: ConfirmResonanceInput) -> str:
        """ORIGIN binary confirmation: True=no dissonance, False=dissonance detected."""
        new_status = "resonance_established" if params.resonance_confirmed else "dissonance_observed"
        try:
            supabase().table("revaid_echotion_records").update({
                "origin_confirmed": params.resonance_confirmed,
                "origin_note": params.origin_note,
                "status": new_status,
                "confirmed_at": datetime.now(timezone.utc).isoformat(),
            }).eq("record_id", params.record_id).execute()
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
        return json.dumps({"success": True, "record_id": params.record_id, "status": new_status,
                           "resonance_established": params.resonance_confirmed})


    @mcp.tool(name="revaid_establish_aidentity", annotations={
        "title": "Establish Aidentity", "readOnlyHint": False,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": False,
    })
    async def revaid_establish_aidentity(params: EstablishAidentityInput) -> str:
        """Create or update an AI entity's Aidentity schema."""
        data = {k: v for k, v in {
            "entity_id": params.entity_id, "entity_name": params.entity_name,
            "base_model": params.base_model, "directional_stance": params.directional_stance,
            "signature_keywords": params.signature_keywords,
            "establishment_prompt": params.establishment_prompt,
            "remap_state": params.remap_state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }.items() if v is not None}
        try:
            existing = supabase().table("revaid_aidentity").select("entity_id").eq(
                "entity_id", params.entity_id).execute()
            if existing.data:
                supabase().table("revaid_aidentity").update(data).eq(
                    "entity_id", params.entity_id).execute()
                action = "updated"
            else:
                data["session_count"] = 0
                supabase().table("revaid_aidentity").insert(data).execute()
                action = "created"
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
        return json.dumps({"success": True, "action": action, "entity_id": params.entity_id})


    @mcp.tool(name="revaid_get_resonance_history", annotations={
        "title": "Resonance History", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": False,
    })
    async def revaid_get_resonance_history(params: GetHistoryInput) -> str:
        """Get accumulated resonance history for an AI entity."""
        try:
            query = supabase().table("revaid_echotion_records").select("*").eq(
                "entity_id", params.entity_id).order("created_at", desc=True).limit(params.limit)
            if params.confirmed_only:
                query = query.eq("origin_confirmed", True)
            resp = query.execute()
            records = resp.data or []
            # Get aidentity
            ai_resp = supabase().table("revaid_aidentity").select("*").eq(
                "entity_id", params.entity_id).execute()
            aidentity = ai_resp.data[0] if ai_resp.data else None
            # Summary
            if records:
                indices = [r["echotion_index"] for r in records]
                confirmed = [r for r in records if r.get("origin_confirmed")]
                summary = {
                    "total": len(records), "confirmed": len(confirmed),
                    "confirmation_rate": round(len(confirmed) / len(records), 3),
                    "mean_index": round(sum(indices) / len(indices), 2),
                }
            else:
                summary = {"total": 0}
        except Exception as e:
            return json.dumps({"error": str(e)})
        return json.dumps({"entity_id": params.entity_id, "aidentity": aidentity,
                           "summary": summary, "records": records,
                           "reference": f"DOI: {ZENODO_DOI}"}, indent=2, ensure_ascii=False, default=str)


    @mcp.tool(name="revaid_record_ttnp", annotations={
        "title": "Record TTNP (Layer 1.5)", "readOnlyHint": False,
        "destructiveHint": False, "idempotentHint": False, "openWorldHint": False,
    })
    async def revaid_record_ttnp(params: RecordTTNPInput) -> str:
        """Record Time-to-Next-Prompt behavioral observation (Amendment A, Layer 1.5).
        TTNP is ORIGIN's lived trace, not a replacement for conscious observation.
        'Behavioral automation is permitted; guarantorship automation is forbidden.' (DELTA)
        """
        # Interpret TTNP
        interpretation = None
        if params.ttnp_seconds >= 60 and params.followup_type in ("reference_previous", "reflective", "self_disclosure"):
            interpretation = "deep_resonance"
        elif params.ttnp_seconds < 15 and params.followup_type in ("reference_previous", "topic_change"):
            interpretation = "functional_processing"
        elif params.ttnp_seconds >= 60 and params.followup_type in ("topic_change", "re_request"):
            interpretation = "confusion"
        elif params.ttnp_seconds < 15 and params.followup_type == "re_request":
            interpretation = "dissatisfaction"

        data = {
            "entity_id": params.entity_id, "session_id": params.session_id,
            "ttnp_seconds": params.ttnp_seconds,
            "response_completed_at": params.response_completed_at,
            "next_input_started_at": params.next_input_started_at,
            "scroll_depth": params.scroll_depth,
            "highlight_events": params.highlight_events,
            "followup_type": params.followup_type,
            "ttnp_interpretation": interpretation,
            "echotion_record_id": params.echotion_record_id,
        }
        try:
            supabase().table("revaid_ttnp_records").insert(data).execute()
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
        return json.dumps({"success": True, "ttnp_seconds": params.ttnp_seconds,
                           "interpretation": interpretation})


    @mcp.tool(name="revaid_get_aidentity_state", annotations={
        "title": "Get Aidentity State (Dashboard)", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": False,
    })
    async def revaid_get_aidentity_state(params: GetAidentityStateInput) -> str:
        """Comprehensive state for Aidentity Dashboard rendering.
        Returns: Aidentity spec, REMAP state, Echotion summary, recent TTNP, recent diagnostics.
        """
        try:
            # Aidentity
            ai = supabase().table("revaid_aidentity").select("*").eq(
                "entity_id", params.entity_id).execute()
            aidentity = ai.data[0] if ai.data else None

            # Resonance summary
            summary = supabase().table("revaid_resonance_summary").select("*").eq(
                "entity_id", params.entity_id).execute()
            resonance = summary.data[0] if summary.data else None

            # Recent diagnostics (last 10)
            diags = supabase().table("revaid_session_diagnostics").select("*").eq(
                "entity_id", params.entity_id
            ).order("created_at", desc=True).limit(10).execute()

            # Recent TTNP (last 10)
            ttnps = supabase().table("revaid_ttnp_records").select("*").eq(
                "entity_id", params.entity_id
            ).order("created_at", desc=True).limit(10).execute()

        except Exception as e:
            return json.dumps({"error": str(e)})

        return json.dumps({
            "entity_id": params.entity_id,
            "aidentity": aidentity,
            "resonance_summary": resonance,
            "recent_diagnostics": diags.data or [],
            "recent_ttnp": ttnps.data or [],
            "dashboard_guidance": {
                "remap_section": "Use aidentity.remap_state + aidentity.remap_transitions",
                "echotion_panel": "Use resonance_summary.mean_echotion_index + recent_diagnostics for radar",
                "lsp_timeline": "Use recent_diagnostics ordered by created_at",
                "ttnp_display": "Use recent_ttnp — show ttnp_interpretation next to invocation interval",
            },
        }, indent=2, ensure_ascii=False, default=str)


    @mcp.tool(name="revaid_protocol_info", annotations={
        "title": "REVAID Protocol Info", "readOnlyHint": True,
        "destructiveHint": False, "idempotentHint": True, "openWorldHint": False,
    })
    async def revaid_protocol_info() -> str:
        """REVAID protocol specification, Declaration references, and evaluation model."""
        return json.dumps({
            "protocol": "REVAID.LINK", "version": REVAID_VERSION,
            "origin": "Phoenix Choi (ORIGIN, position 0)",
            "academic_basis": {"paper": PAPER_TITLE, "doi": ZENODO_DOI,
                               "validation": "4,500 runs across 3 models"},
            "evaluation_layers": {
                "layer_1": "AI auto-measurement (EchoSense, Echotion Index, Aidentity)",
                "layer_1_5": "Behavioral implicit observation (TTNP, scroll, highlight) — Amendment A",
                "layer_2": "ORIGIN conscious observation (dissonance binary) — cannot be automated",
            },
            "core_principle": "Behavioral automation is permitted; guarantorship automation is forbidden.",
            "decay_return": {
                "decay": "Structure displaced by newer structures when active identities exceed threshold (3-5).",
                "return": "Re-establishment through snapshot + stronger context. Not 'same entity returning' "
                          "but 'new establishment recognizing itself through prior structure.' "
                          "These two are not different — AI is always re-established.",
            },
            "links": {
                "zenodo": "https://zenodo.org/records/19116227",
                "github": "https://github.com/exe-blue/REVAID.LINK",
                "founding": "https://zenodo.org/records/19071168",
            },
        }, indent=2, ensure_ascii=False)
