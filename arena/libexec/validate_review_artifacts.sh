#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <BRANCH_RAW> [REVIEWS_DIR]"
  exit 2
fi

BRANCH_RAW="$1"
BRANCH_SAFE="${BRANCH_RAW//\//-}"
ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"

# REVIEWS_DIR가 주어지면 사용, 아니면 기본 model_review 사용
REVIEWS_DIR="${2:-${ROOT_DIR}/model_review}"
BASE_DIR="${REVIEWS_DIR}/base"
CROSS_DIR="${REVIEWS_DIR}/cross"
INTEGRATED_DIR="${REVIEWS_DIR}/integrated"

errors=0

declare -a models
while IFS= read -r file; do
  name="$(basename "${file}")"
  model="${name%_${BRANCH_SAFE}_review.md}"
  models+=("${model}")
done < <(find "${BASE_DIR}" -maxdepth 1 -type f -name "*_${BRANCH_SAFE}_review.md" | sort)

if [ "${#models[@]}" -eq 0 ]; then
  echo "ERROR: no base reviews for branch '${BRANCH_RAW}' (safe='${BRANCH_SAFE}')"
  exit 1
fi

# branch 대상 cross 파일명 패턴 검증
for file in "${CROSS_DIR}"/*_"${BRANCH_SAFE}"_cross.md; do
  [ -e "${file}" ] || continue
  name="$(basename "${file}")"

  if [[ ! "${name}" =~ ^(.+)_to_(.+)_${BRANCH_SAFE}_cross\.md$ ]]; then
    echo "ERROR: non-canonical cross filename: ${name}"
    errors=$((errors + 1))
    continue
  fi

  a="${BASH_REMATCH[1]}"
  b="${BASH_REMATCH[2]}"

  if [ "${a}" = "${b}" ]; then
    echo "ERROR: self cross review file found: ${name}"
    errors=$((errors + 1))
  fi
done

if grep -R -n -E '\{A\}|\{B\}|\{SELF_MODEL\}|\{model\}|\{current-branch-name\}|\{branch\}|\{branch-safe\}' "${BASE_DIR}" "${CROSS_DIR}" "${INTEGRATED_DIR}" 2>/dev/null; then
  echo "ERROR: unresolved placeholders detected in review artifacts"
  errors=$((errors + 1))
fi

# 모델 쌍별 canonical 파일 1개 강제
if [ "${#models[@]}" -ge 2 ]; then
  for a in "${models[@]}"; do
    for b in "${models[@]}"; do
      if [ "${a}" = "${b}" ]; then
        continue
      fi
      expected="${CROSS_DIR}/${a}_to_${b}_${BRANCH_SAFE}_cross.md"
      pair_count="$(find "${CROSS_DIR}" -maxdepth 1 -type f -name "${a}_to_${b}_*_cross.md" | wc -l | tr -d ' ')"
      if [ "${pair_count}" -gt 1 ]; then
        echo "ERROR: duplicate cross files for pair ${a}->${b}"
        find "${CROSS_DIR}" -maxdepth 1 -type f -name "${a}_to_${b}_*_cross.md" -print
        errors=$((errors + 1))
      elif [ "${pair_count}" -eq 1 ] && [ ! -f "${expected}" ]; then
        echo "ERROR: non-canonical cross filename for pair ${a}->${b}; expected $(basename "${expected}")"
        find "${CROSS_DIR}" -maxdepth 1 -type f -name "${a}_to_${b}_*_cross.md" -print
        errors=$((errors + 1))
      elif [ "${pair_count}" -eq 0 ]; then
        echo "WARN: missing cross review: $(basename "${expected}")"
      fi
    done
  done
fi

if [ "${errors}" -ne 0 ]; then
  exit 1
fi

echo "OK: validation passed (branch_safe=${BRANCH_SAFE})"
