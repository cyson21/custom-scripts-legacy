#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 3 ]; then
  echo "Usage: $0 <SELF_MODEL|auto> <B_MODEL|auto> <BRANCH_RAW> [REVIEWS_DIR]"
  exit 2
fi

SELF_MODEL="$1"
B_MODEL="$2"
BRANCH_RAW="$3"
BRANCH_SAFE="${BRANCH_RAW//\//-}"
ROOT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"

# REVIEWS_DIR가 주어지면 사용, 아니면 기본 model_review 사용
REVIEWS_DIR="${4:-${ROOT_DIR}/model_review}"
BASE_DIR="${REVIEWS_DIR}/base"
CROSS_DIR="${REVIEWS_DIR}/cross"
TARGET_FILE=""
OUTPUT_FILE=""

if [[ "${SELF_MODEL}" =~ [\{\}] ]] || [[ "${B_MODEL}" =~ [\{\}] ]] || [[ "${BRANCH_RAW}" =~ [\{\}] ]] || [[ "${BRANCH_SAFE}" =~ [\{\}] ]]; then
  echo "INPUT_ERROR: unresolved variables"
  exit 1
fi

if [ -z "${SELF_MODEL}" ] || [ -z "${B_MODEL}" ] || [ -z "${BRANCH_RAW}" ] || [ -z "${BRANCH_SAFE}" ]; then
  echo "INPUT_ERROR: unresolved variables"
  exit 1
fi

declare -a base_models
while IFS= read -r file; do
  name="$(basename "${file}")"
  model="${name%_${BRANCH_SAFE}_review.md}"
  base_models+=("${model}")
done < <(find "${BASE_DIR}" -maxdepth 1 -type f -name "*_${BRANCH_SAFE}_review.md" | sort)

if [ "${#base_models[@]}" -eq 0 ]; then
  echo "INPUT_ERROR: base review file not found"
  echo "No base reviews for branch_safe=${BRANCH_SAFE}"
  exit 1
fi

# auto resolution for B_MODEL
if [ "${B_MODEL}" = "auto" ]; then
  if [ "${SELF_MODEL}" = "auto" ]; then
    echo "INPUT_ERROR: cannot auto-resolve both SELF_MODEL and B_MODEL"
    exit 1
  fi
  declare -a b_candidates=()
  for m in "${base_models[@]}"; do
    if [ "${m}" != "${SELF_MODEL}" ]; then
      b_candidates+=("${m}")
    fi
  done

  if [ "${#b_candidates[@]}" -eq 0 ]; then
    echo "INPUT_ERROR: no B_MODEL candidate found"
    exit 1
  fi

  if [ "${#b_candidates[@]}" -eq 1 ]; then
    B_MODEL="${b_candidates[0]}"
  else
    # 3+ 모델일 때: 아직 SELF_MODEL이 리뷰하지 않은 대상 중 사전순 1개 선택
    declare -a pending_candidates=()
    for m in "${b_candidates[@]}"; do
      expected_cross="${CROSS_DIR}/${SELF_MODEL}_to_${m}_${BRANCH_SAFE}_cross.md"
      if [ ! -f "${expected_cross}" ]; then
        pending_candidates+=("${m}")
      fi
    done

    if [ "${#pending_candidates[@]}" -eq 0 ]; then
      echo "INPUT_ERROR: no pending B_MODEL for SELF_MODEL=${SELF_MODEL}"
      exit 1
    fi

    IFS=$'\n' sorted=($(printf '%s\n' "${pending_candidates[@]}" | sort))
    unset IFS
    B_MODEL="${sorted[0]}"
  fi

  if [ -z "${B_MODEL}" ]; then
    echo "INPUT_ERROR: B_MODEL is ambiguous"
    printf 'Candidates: %s\n' "${b_candidates[@]}"
    exit 1
  fi
fi

# auto resolution for SELF_MODEL
if [ "${SELF_MODEL}" = "auto" ]; then
  declare -a self_candidates=()
  for m in "${base_models[@]}"; do
    if [ "${m}" != "${B_MODEL}" ]; then
      self_candidates+=("${m}")
    fi
  done
  if [ "${#self_candidates[@]}" -ne 1 ]; then
    echo "INPUT_ERROR: SELF_MODEL is ambiguous"
    printf 'Candidates: %s\n' "${self_candidates[@]}"
    exit 1
  fi
  SELF_MODEL="${self_candidates[0]}"
fi

if [ "${SELF_MODEL}" = "${B_MODEL}" ]; then
  echo "INPUT_ERROR: self review is not allowed (${SELF_MODEL} -> ${B_MODEL})"
  exit 1
fi

TARGET_FILE="${BASE_DIR}/${B_MODEL}_${BRANCH_SAFE}_review.md"
OUTPUT_FILE="${CROSS_DIR}/${SELF_MODEL}_to_${B_MODEL}_${BRANCH_SAFE}_cross.md"

if [ ! -f "${TARGET_FILE}" ]; then
  echo "INPUT_ERROR: base review file not found"
  echo "Expected: ${TARGET_FILE}"
  echo "Available base reviews:"
  ls -1 "${BASE_DIR}" || true
  exit 1
fi

# 동일 pair/branch에 대해 non-canonical 파일이 이미 있으면 중단
duplicates="$(find "${CROSS_DIR}" -maxdepth 1 -type f -name "${SELF_MODEL}_to_${B_MODEL}_*_cross.md" | wc -l | tr -d ' ')"
if [ "${duplicates}" -gt 0 ] && [ ! -f "${OUTPUT_FILE}" ]; then
  echo "INPUT_ERROR: non-canonical or duplicate cross file exists for pair"
  find "${CROSS_DIR}" -maxdepth 1 -type f -name "${SELF_MODEL}_to_${B_MODEL}_*_cross.md" -print
  echo "Expected canonical output: ${OUTPUT_FILE}"
  exit 1
fi

echo "OK: preflight passed"
echo "SELF_MODEL=${SELF_MODEL}"
echo "B_MODEL=${B_MODEL}"
echo "BRANCH_RAW=${BRANCH_RAW}"
echo "BRANCH_SAFE=${BRANCH_SAFE}"
echo "INPUT_FILE=${TARGET_FILE}"
echo "OUTPUT_FILE=${OUTPUT_FILE}"
