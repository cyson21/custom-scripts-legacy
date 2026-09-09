import re
from orchestrator.core.models import ConsensusResult
from radon.visitors import ComplexityVisitor
from radon.metrics import mi_visit


SECTION_AGREED = "### 1. 동의하는 핵심"
SECTION_ISSUES = "### 2. 문제점 또는 누락"


def _reconstruct_code_from_diff(diff_text: str) -> str:
    """
    Naively reconstructs the new version of a file from a diff text.
    This is not robust but required for static analysis.
    """
    new_code_lines = []
    for line in diff_text.splitlines():
        if line.startswith('---') or line.startswith('+++') or line.startswith('@@'):
            continue
        if not line.startswith('-'):
            new_code_lines.append(line[1:] if line.startswith('+') else line)
    return "\n".join(new_code_lines)


def score_diff_quality(diff: str) -> float:
    """
    Scores the quality of a diff based on complexity and maintainability.
    Uses radon for static analysis.
    Returns a score between 0.0 and 1.0.
    """
    new_code = _reconstruct_code_from_diff(diff)
    if not new_code.strip():
        return 0.5  # Neutral score for empty diffs/deletions

    try:
        # 1. Maintainability Index (higher is better)
        mi_score = mi_visit(new_code, multi=True)
        # Normalize MI score (0-100) to a bonus (0.0-0.4)
        mi_bonus = (mi_score / 100.0) * 0.4

        # 2. Cyclomatic Complexity (lower is better)
        visitor = ComplexityVisitor.from_code(new_code)
        total_complexity = 0
        func_count = 0
        for f in visitor.functions:
            total_complexity += f.complexity
            func_count += 1
        
        # Penalize high complexity. A small penalty for moderate complexity,
        # and a larger one for high complexity.
        # Average complexity is a good indicator.
        avg_complexity = (total_complexity / func_count) if func_count > 0 else 0
        
        complexity_penalty = 0.0
        if avg_complexity > 10:
            complexity_penalty = 0.3
        elif avg_complexity > 5:
            complexity_penalty = 0.15
        
        # Base score of 0.5, adjust with bonus and penalty
        base_score = 0.5
        final_score = base_score + mi_bonus - complexity_penalty
        
        return max(0.0, min(1.0, final_score))

    except Exception:
        # If radon fails to parse the code, it's likely a partial
        # or invalid diff. Return a low score.
        return 0.1


def _extract_bullets(section_title: str, text: str) -> list[str]:
    lines = text.splitlines()
    collected: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### "):
            in_section = stripped.startswith(section_title)
            continue
        if in_section and stripped.startswith("- "):
            collected.append(stripped[2:].strip())
    return collected


def judge_consensus(
    answers: dict[str, str],
    reviews: dict[str, str],
) -> ConsensusResult:
    """
    Evaluates consensus among multiple models.
    Returns a ConsensusResult with a score based on agreement.
    """
    all_shared_points = []
    all_open_issues = []
    
    for model_name, review in reviews.items():
        all_shared_points.extend(_extract_bullets(SECTION_AGREED, review))
        all_open_issues.extend(_extract_bullets(SECTION_ISSUES, review))

    # Deduplicate points
    shared_points = sorted(list(set(all_shared_points)))
    open_issues = sorted(list(set(all_open_issues)))

    # Basic scoring logic: 
    # Points add to score, issues subtract from it.
    review_score = 0.5
    point_bonus = len(shared_points) * 0.1
    issue_penalty = len(open_issues) * 0.15
    review_score = max(0.0, min(1.0, review_score + point_bonus - issue_penalty))
    
    # Score diff quality
    diff_text = list(answers.values())[0] if answers else ""
    diff_quality_score = score_diff_quality(diff_text)
    
    # Final score is a weighted average
    score = (review_score * 0.6) + (diff_quality_score * 0.4)

    # Recommendation logic:
    # If high score, pick the first answer (usually primary model)
    # If low score, we might need more rounds or human intervention
    if score >= 0.8:
        status = "agree"
    elif score >= 0.4:
        status = "soft_agree"
    else:
        status = "disagree"

    recommended = list(answers.values())[0] if answers else ""

    return ConsensusResult(
        status=status,
        score=round(score, 2),
        shared_points=shared_points,
        open_issues=open_issues,
        recommended_final=recommended,
    )
