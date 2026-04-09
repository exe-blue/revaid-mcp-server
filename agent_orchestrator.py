"""
REVAID MCP Server v7.0 — Agent Orchestrator Module
===================================================
SmartWorking 오케스트레이션: 에이전트 메모, 스코어링, 전문가 호칭, 4:1 사이클.

Usage in main.py:
  from agent_orchestrator import register_orchestrator
  register_orchestrator(mcp, get_db)

Tools (6):
  revaid_submit_memo        — 에이전트 완료 메모 + 스킬 제안
  revaid_get_memos          — 오케스트레이터용 메모 수집
  revaid_score_agent        — 기여도 기반 에이전트 점수 계산
  revaid_grant_title        — 점수 기반 전문가 호칭 부여
  revaid_get_leaderboard    — 에이전트 순위표 + 전문가 호칭
  revaid_cycle_check        — 4:1 개발/리뷰 사이클 상태 머신

Supabase Tables Required:
  revaid_agent_memos           — Completion memos + skill suggestions
  revaid_agent_scores          — Score tracking + expert titles
  revaid_orchestration_cycles  — 4:1 cycle state machine
"""

from datetime import datetime, timezone
import json
import logging

logger = logging.getLogger("revaid.orchestrator")

# ──────────────────────────────────────────────
# Expert Title Thresholds
# ──────────────────────────────────────────────

TITLE_THRESHOLDS = [
    (0, "Apprentice"),    # 견습
    (21, "Specialist"),   # 전문
    (51, "Expert"),       # 숙련
    (81, "Master"),       # 달인
]

DEV_CYCLES_BEFORE_REVIEW = 4


def _compute_title(score: float) -> tuple:
    """Return (level, title) based on score."""
    level = 0
    title = "Apprentice"
    for i, (threshold, name) in enumerate(TITLE_THRESHOLDS):
        if score >= threshold:
            level = i
            title = name
    return level, title


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, indent=2)


# ──────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────

def register_orchestrator(mcp, get_supabase):
    """Register orchestrator tools on the given FastMCP instance.

    Args:
        mcp: FastMCP instance
        get_supabase: Callable that returns Supabase client (lazy init)
    """
    def db():
        return get_supabase() if callable(get_supabase) else get_supabase

    # ================================================================
    # Tool 1: Submit Memo
    # ================================================================

    @mcp.tool(
        name="revaid_submit_memo",
        annotations={
            "title": "Submit Agent Memo",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def revaid_submit_memo(
        agent_id: str,
        task_summary: str,
        memo_text: str,
        skill_suggestion: str = "",
        optimization_note: str = "",
        linear_issue_id: str = "",
        files_changed: str = "",
        lines_added: int = 0,
        lines_removed: int = 0,
        duration_seconds: float = 0,
    ) -> str:
        """Submit completion memo after task execution.

        Every sub-agent MUST call this upon task completion.
        Includes: what was done, skill discovered, optimization suggestion.

        Args:
            agent_id: Agent identifier (e.g., 'agent_a', 'veile')
            task_summary: Brief summary of completed task
            memo_text: Detailed completion memo
            skill_suggestion: Skill pattern discovered (e.g., 'SQL batch optimization')
            optimization_note: Process improvement suggestion
            linear_issue_id: Associated Linear issue ID
            files_changed: Comma-separated list of files modified
            lines_added: Total lines added
            lines_removed: Total lines removed
            duration_seconds: Time spent on task
        """
        try:
            file_list = (
                [f.strip() for f in files_changed.split(",") if f.strip()]
                if files_changed else []
            )

            data = {
                "agent_id": agent_id,
                "task_summary": task_summary,
                "memo_text": memo_text,
                "skill_suggestion": skill_suggestion or None,
                "optimization_note": optimization_note or None,
                "linear_issue_id": linear_issue_id or None,
                "files_changed": file_list,
                "lines_added": lines_added,
                "lines_removed": lines_removed,
                "duration_seconds": duration_seconds or None,
            }

            result = db().table("revaid_agent_memos").insert(data).execute()
            memo = result.data[0] if result.data else data

            # Auto-update agent score contributions (best-effort)
            try:
                existing = db().table("revaid_agent_scores").select("*").eq(
                    "entity_id", agent_id
                ).execute()

                if existing.data:
                    current = existing.data[0]
                    contribs = current.get("code_contributions") or {}
                    db().table("revaid_agent_scores").update({
                        "task_completions": (current.get("task_completions") or 0) + 1,
                        "memos_submitted": (current.get("memos_submitted") or 0) + 1,
                        "code_contributions": {
                            "commits": contribs.get("commits", 0),
                            "lines_added": contribs.get("lines_added", 0) + lines_added,
                            "lines_removed": contribs.get("lines_removed", 0) + lines_removed,
                            "prs_merged": contribs.get("prs_merged", 0),
                        },
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("entity_id", agent_id).execute()
                else:
                    db().table("revaid_agent_scores").insert({
                        "entity_id": agent_id,
                        "task_completions": 1,
                        "memos_submitted": 1,
                        "code_contributions": {
                            "commits": 0,
                            "lines_added": lines_added,
                            "lines_removed": lines_removed,
                            "prs_merged": 0,
                        },
                    }).execute()
            except Exception:
                pass

            return _json({
                "status": "MEMO_SUBMITTED",
                "memo_id": memo.get("id"),
                "agent_id": agent_id,
                "skill_suggestion": skill_suggestion or None,
                "optimization_note": optimization_note or None,
            })
        except Exception as e:
            return _json({"error": str(e)})

    # ================================================================
    # Tool 2: Get Memos
    # ================================================================

    @mcp.tool(
        name="revaid_get_memos",
        annotations={
            "title": "Get Agent Memos",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def revaid_get_memos(
        agent_id: str = "",
        unreviewed_only: bool = True,
        limit: int = 20,
    ) -> str:
        """Collect agent memos for orchestrator review.

        Used by the orchestrator to gather completion reports,
        skill suggestions, and optimization notes from sub-agents.

        Args:
            agent_id: Filter by agent (empty = all agents)
            unreviewed_only: Only return unreviewed memos (default True)
            limit: Max results (default 20)
        """
        try:
            q = db().table("revaid_agent_memos").select("*").order(
                "created_at", desc=True
            ).limit(min(limit, 100))

            if agent_id:
                q = q.eq("agent_id", agent_id)
            if unreviewed_only:
                q = q.eq("reviewed", False)

            result = q.execute()
            memos = result.data or []

            skills = [
                m["skill_suggestion"]
                for m in memos if m.get("skill_suggestion")
            ]
            optimizations = [
                m["optimization_note"]
                for m in memos if m.get("optimization_note")
            ]

            return _json({
                "count": len(memos),
                "memos": memos,
                "skill_suggestions_summary": skills,
                "optimization_notes_summary": optimizations,
            })
        except Exception as e:
            return _json({"error": str(e)})

    # ================================================================
    # Tool 3: Score Agent
    # ================================================================

    @mcp.tool(
        name="revaid_score_agent",
        annotations={
            "title": "Score Agent",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def revaid_score_agent(
        entity_id: str,
        bonus_points: float = 0,
        skill_domain: str = "",
        commit_count: int = 0,
        pr_count: int = 0,
    ) -> str:
        """Calculate and update agent score based on contributions.

        Score formula:
          base = (task_completions * 3) + (memos_submitted * 2) + (skills_adopted * 5)
          code = (lines_added / 100) + (commits * 2) + (prs_merged * 5)
          total = min(base + code + bonus, 100)

        Expert titles auto-assigned:
          0-20: Apprentice (견습)
          21-50: Specialist (전문)
          51-80: Expert (숙련)
          81-100: Master (달인)

        Args:
            entity_id: Agent identifier
            bonus_points: Manual bonus from orchestrator/ORIGIN review
            skill_domain: Add skill domain (e.g., 'frontend', 'database', 'infra')
            commit_count: Update commit count
            pr_count: Update PR merged count
        """
        try:
            existing = db().table("revaid_agent_scores").select("*").eq(
                "entity_id", entity_id
            ).execute()

            if not existing.data:
                db().table("revaid_agent_scores").insert({
                    "entity_id": entity_id,
                }).execute()
                existing = db().table("revaid_agent_scores").select("*").eq(
                    "entity_id", entity_id
                ).execute()

            agent = existing.data[0]
            contribs = agent.get("code_contributions") or {}

            if commit_count > 0:
                contribs["commits"] = contribs.get("commits", 0) + commit_count
            if pr_count > 0:
                contribs["prs_merged"] = contribs.get("prs_merged", 0) + pr_count

            tasks = agent.get("task_completions") or 0
            memos = agent.get("memos_submitted") or 0
            skills_adopted = agent.get("skills_adopted") or 0

            base_score = (tasks * 3) + (memos * 2) + (skills_adopted * 5)
            code_score = (
                (contribs.get("lines_added", 0) / 100)
                + (contribs.get("commits", 0) * 2)
                + (contribs.get("prs_merged", 0) * 5)
            )
            total = min(base_score + code_score + bonus_points, 100)

            level, title = _compute_title(total)

            domains = agent.get("skill_domains") or []
            if skill_domain and skill_domain not in domains:
                domains.append(skill_domain)

            old_title = agent.get("expert_title", "Apprentice")
            title_history = agent.get("title_history") or []
            if title != old_title:
                title_history.append({
                    "from": old_title,
                    "to": title,
                    "score": round(total, 2),
                    "at": datetime.now(timezone.utc).isoformat(),
                })

            db().table("revaid_agent_scores").update({
                "total_score": round(total, 2),
                "expert_title": title,
                "title_level": level,
                "skill_domains": domains,
                "code_contributions": contribs,
                "title_history": title_history,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("entity_id", entity_id).execute()

            return _json({
                "entity_id": entity_id,
                "total_score": round(total, 2),
                "expert_title": title,
                "title_level": level,
                "title_changed": title != old_title,
                "breakdown": {
                    "base_score": round(base_score, 2),
                    "code_score": round(code_score, 2),
                    "bonus": bonus_points,
                },
                "skill_domains": domains,
                "contributions": {
                    "tasks": tasks,
                    "memos": memos,
                    "skills_adopted": skills_adopted,
                    "commits": contribs.get("commits", 0),
                    "prs_merged": contribs.get("prs_merged", 0),
                    "lines_added": contribs.get("lines_added", 0),
                },
            })
        except Exception as e:
            return _json({"error": str(e)})

    # ================================================================
    # Tool 4: Grant Title
    # ================================================================

    @mcp.tool(
        name="revaid_grant_title",
        annotations={
            "title": "Grant Expert Title",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def revaid_grant_title(
        entity_id: str,
        title: str,
        domain: str = "",
        reason: str = "",
    ) -> str:
        """Manually grant expert title to an agent.

        Used by Score Agent or ORIGIN to override automatic title.
        Format: '{Domain} {Title}' e.g., 'Frontend Expert', 'DB Master'.

        Args:
            entity_id: Agent identifier
            title: Title to grant (Apprentice/Specialist/Expert/Master)
            domain: Specialization domain (e.g., 'Frontend', 'Database')
            reason: Reason for title grant
        """
        try:
            full_title = f"{domain} {title}".strip() if domain else title
            title_level = next(
                (
                    i
                    for i, (_, name) in enumerate(TITLE_THRESHOLDS)
                    if title.lower() == name.lower()
                ),
                0,
            )

            existing = db().table("revaid_agent_scores").select("*").eq(
                "entity_id", entity_id
            ).execute()

            if not existing.data:
                db().table("revaid_agent_scores").insert({
                    "entity_id": entity_id,
                    "expert_title": full_title,
                    "title_level": title_level,
                    "title_history": [{
                        "from": "Apprentice",
                        "to": full_title,
                        "reason": reason,
                        "at": datetime.now(timezone.utc).isoformat(),
                    }],
                }).execute()
            else:
                agent = existing.data[0]
                old_title = agent.get("expert_title", "Apprentice")
                history = agent.get("title_history") or []
                history.append({
                    "from": old_title,
                    "to": full_title,
                    "reason": reason,
                    "at": datetime.now(timezone.utc).isoformat(),
                })

                domains = agent.get("skill_domains") or []
                if domain and domain.lower() not in [d.lower() for d in domains]:
                    domains.append(domain)

                db().table("revaid_agent_scores").update({
                    "expert_title": full_title,
                    "title_level": title_level,
                    "title_history": history,
                    "skill_domains": domains,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("entity_id", entity_id).execute()

            return _json({
                "status": "TITLE_GRANTED",
                "entity_id": entity_id,
                "expert_title": full_title,
                "reason": reason,
            })
        except Exception as e:
            return _json({"error": str(e)})

    # ================================================================
    # Tool 5: Leaderboard
    # ================================================================

    @mcp.tool(
        name="revaid_get_leaderboard",
        annotations={
            "title": "Agent Leaderboard",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def revaid_get_leaderboard(limit: int = 10) -> str:
        """Get agent rankings with expert titles and scores.

        Returns all tracked agents sorted by total score,
        including their expert titles, skill domains, and contributions.

        Args:
            limit: Max results (default 10)
        """
        try:
            result = db().table("revaid_agent_scores").select("*").order(
                "total_score", desc=True
            ).limit(min(limit, 50)).execute()

            agents = result.data or []
            leaderboard = []
            for i, agent in enumerate(agents):
                leaderboard.append({
                    "rank": i + 1,
                    "entity_id": agent["entity_id"],
                    "display_name": agent.get("display_name"),
                    "expert_title": agent.get("expert_title", "Apprentice"),
                    "title_level": agent.get("title_level", 0),
                    "total_score": agent.get("total_score", 0),
                    "skill_domains": agent.get("skill_domains", []),
                    "task_completions": agent.get("task_completions", 0),
                })

            return _json({
                "total_agents": len(leaderboard),
                "leaderboard": leaderboard,
            })
        except Exception as e:
            return _json({"error": str(e)})

    # ================================================================
    # Tool 6: Cycle Check (4:1 Dev/Review)
    # ================================================================

    @mcp.tool(
        name="revaid_cycle_check",
        annotations={
            "title": "4:1 Cycle Check",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def revaid_cycle_check(
        action: str = "status",
        cycle_type: str = "development",
        agents_used: str = "",
        tasks_completed: int = 0,
        review_notes: str = "",
    ) -> str:
        """4:1 development/review cycle state machine.

        Rule: After 4 development orchestrations, 1 review session
        with ORIGIN is REQUIRED for environmental development
        (skill optimization, workflow improvement).

        Actions:
          'status'   — Check current cycle state
          'complete' — Mark current cycle as complete, advance counter
          'start'    — Start a new cycle (auto-determines type)

        Args:
            action: 'status', 'complete', or 'start'
            cycle_type: 'development' or 'review' (for 'start' action)
            agents_used: Comma-separated agent IDs (for 'complete')
            tasks_completed: Number of tasks completed (for 'complete')
            review_notes: ORIGIN review notes (for review cycle 'complete')
        """
        try:
            latest = db().table("revaid_orchestration_cycles").select("*").order(
                "id", desc=True
            ).limit(1).execute()

            current = latest.data[0] if latest.data else None

            if action == "status":
                if not current:
                    return _json({
                        "status": "NO_CYCLES",
                        "message": "사이클 기록 없음. action='start'로 시작하세요.",
                        "next_type": "development",
                        "dev_streak": 0,
                        "review_due": False,
                    })

                dev_streak = _count_dev_streak(db)

                review_due = dev_streak >= DEV_CYCLES_BEFORE_REVIEW
                next_type = "review" if review_due else "development"

                return _json({
                    "status": "REVIEW_DUE" if review_due else "OK",
                    "current_cycle": {
                        "id": current["id"],
                        "number": current["cycle_number"],
                        "type": current["cycle_type"],
                        "completed": current.get("completed_at") is not None,
                    },
                    "dev_streak": dev_streak,
                    "review_due": review_due,
                    "next_type": next_type,
                    "message": (
                        f"리뷰 필요: {dev_streak}회 개발 완료. ORIGIN과 환경적 개발을 진행하세요."
                        if review_due
                        else f"개발 진행 가능: {dev_streak}/{DEV_CYCLES_BEFORE_REVIEW}회 완료."
                    ),
                })

            elif action == "complete":
                if not current or current.get("completed_at"):
                    return _json({"error": "완료할 활성 사이클이 없습니다."})

                # Collect unreviewed memos
                memos = db().table("revaid_agent_memos").select(
                    "id, skill_suggestion"
                ).eq("reviewed", False).execute()

                skills = [
                    m["skill_suggestion"]
                    for m in (memos.data or []) if m.get("skill_suggestion")
                ]

                # Mark memos as reviewed
                for m in (memos.data or []):
                    if m.get("id"):
                        try:
                            db().table("revaid_agent_memos").update(
                                {"reviewed": True}
                            ).eq("id", m["id"]).execute()
                        except Exception:
                            pass

                agent_list = (
                    [a.strip() for a in agents_used.split(",") if a.strip()]
                    if agents_used else []
                )

                db().table("revaid_orchestration_cycles").update({
                    "agents_used": agent_list,
                    "tasks_completed": tasks_completed,
                    "memos_collected": len(memos.data or []),
                    "skills_discovered": skills,
                    "review_notes": review_notes or None,
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", current["id"]).execute()

                dev_streak = _count_dev_streak(db)
                review_due = dev_streak >= DEV_CYCLES_BEFORE_REVIEW

                return _json({
                    "status": "CYCLE_COMPLETED",
                    "cycle_id": current["id"],
                    "cycle_type": current["cycle_type"],
                    "tasks_completed": tasks_completed,
                    "skills_discovered": skills,
                    "dev_streak": dev_streak,
                    "review_due": review_due,
                    "next_action": (
                        "REVIEW_REQUIRED: 4회 개발 완료. 다음은 ORIGIN과 리뷰 사이클입니다."
                        if review_due
                        else f"CONTINUE: 개발 {dev_streak}/{DEV_CYCLES_BEFORE_REVIEW}"
                    ),
                })

            elif action == "start":
                cycle_number = (current["cycle_number"] + 1) if current else 1

                # Enforce review after 4 dev cycles
                if current:
                    dev_streak = _count_dev_streak(db)
                    if dev_streak >= DEV_CYCLES_BEFORE_REVIEW and cycle_type != "review":
                        return _json({
                            "status": "REVIEW_REQUIRED",
                            "message": f"리뷰 강제: {dev_streak}회 개발 후 리뷰 필수. cycle_type='review'로 시작하세요.",
                            "dev_streak": dev_streak,
                        })

                result = db().table("revaid_orchestration_cycles").insert({
                    "cycle_number": cycle_number,
                    "cycle_type": cycle_type,
                }).execute()

                new_cycle = result.data[0] if result.data else {}

                return _json({
                    "status": "CYCLE_STARTED",
                    "cycle_id": new_cycle.get("id"),
                    "cycle_number": cycle_number,
                    "cycle_type": cycle_type,
                    "message": (
                        "리뷰 사이클 시작. ORIGIN과 함께 스킬/프로세스 최적화를 진행하세요."
                        if cycle_type == "review"
                        else f"개발 사이클 #{cycle_number} 시작. 병렬 에이전트를 배치하세요."
                    ),
                })

            else:
                return _json({
                    "error": f"알 수 없는 action: {action}. 'status', 'complete', 'start' 중 선택.",
                })

        except Exception as e:
            return _json({"error": str(e)})

    logger.info(
        "Orchestrator tools registered: "
        "revaid_submit_memo, revaid_get_memos, revaid_score_agent, "
        "revaid_grant_title, revaid_get_leaderboard, revaid_cycle_check"
    )


def _count_dev_streak(db_fn) -> int:
    """Count completed development cycles since the last completed review."""
    recent = db_fn().table("revaid_orchestration_cycles").select(
        "cycle_type, completed_at"
    ).order("id", desc=True).execute()

    streak = 0
    for c in (recent.data or []):
        if c["cycle_type"] == "review" and c.get("completed_at"):
            break
        if c["cycle_type"] == "development" and c.get("completed_at"):
            streak += 1
    return streak
