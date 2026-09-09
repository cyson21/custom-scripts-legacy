# 프롬프트 템플릿 (복붙 전용)

## 1) 베이스 리뷰 (완전자동)

```text
당신은 20년차 시니어 백엔드 엔지니어입니다.
아래 값을 자동 계산해서 base 리뷰를 작성하세요.

자동 계산 규칙:
1) SELF_MODEL: 현재 세션의 실제 모델 식별자
2) BRANCH: `git branch --show-current`
3) BRANCH_SAFE: BRANCH에서 `/`를 `-`로 치환

템플릿:
- ./scripts/arena/templates/BASE_REVIEW_TEMPLATE.md

규칙:
- 리뷰어_모델에는 SELF_MODEL을 그대로 기록
- 리뷰어_페르소나에는 `20년차 시니어 백엔드 엔지니어` 기록
- 존재하지 않는 메서드/에러코드/API 제안 금지
- evidence는 절대경로 + line
- 표(`이슈 요약표`)는 요약만 기록 (셀당 1문장/짧은 구)
- 상세 근거/재현/영향/수정안은 반드시 `이슈 상세` 섹션에 작성
- 심각도는 아래 3개 문구만 허용:
  - `P1: 매우 심각 (릴리즈/머지 차단급, 즉시 수정)`
  - `P2: 보통 (중요하지만 단기 내 계획 수정 가능, 보통 다음 배포 전)`
  - `P3: 경미 (개선/리팩터링 성격, 후속 처리 가능)`

출력 파일(1개만):
- {REVIEWS_DIR}/base/{SELF_MODEL}_{BRANCH_SAFE}_review.md
```

## 2) 교차 리뷰 (완전자동)

```text
아래 절차를 자동 수행해 cross 리뷰를 작성하세요. 사용자에게 변수 입력을 요구하지 마세요.

자동 계산 규칙:
1) SELF_MODEL: 현재 세션의 실제 모델 식별자
2) BRANCH: `git branch --show-current`
3) BRANCH_SAFE: BRANCH에서 `/`를 `-`로 치환
4) B_MODEL 자동 선택:
   - 아래 명령을 실행해 B_MODEL을 자동 계산
   - `bash ./scripts/arena/libexec/preflight_cross_review.sh "$SELF_MODEL" auto "$BRANCH" "{REVIEWS_DIR}"`
   - preflight가 `B_MODEL=...`와 `OUTPUT_FILE=...`를 출력하면 그 값을 사용
   - 실패 시 에러 문구만 출력하고 중단

검토 입력(자동 계산 결과 사용):
- {REVIEWS_DIR}/base/{B_MODEL}_{BRANCH_SAFE}_review.md

출력 템플릿:
- ./scripts/arena/templates/CROSS_REVIEW_TEMPLATE.md

규칙:
- 메타: 리뷰어_모델=SELF_MODEL, 검토대상_모델=B_MODEL
- 제목/메타: [SELF_MODEL -> B_MODEL]
- decision: AGREE/CHALLENGE/REFINE만 사용
- 표(`검토 요약표`)는 decision 요약만 기록
- 근거/반박/보완 사유는 반드시 `판정 상세` 섹션에 작성
- CHALLENGE/REFINE 항목은 반드시 `이견 이슈 상세` 섹션에 별도 작성
- `이견 이슈 상세`에는 아래를 모두 포함:
  - `최초제기_문제`(배경/발생_조건/실패_양상/근거_코드 포함)
  - `최초제안_조치`(즉시_조치/구조_개선/적용_조건/검증_계획 포함)
  - `연관_파일`
  - `재현_조건`
  - `상세_분석`
  - `영향_평가`
  - `조치_권고`
- 결과 파일은 아래 경로 1개만 생성
- alias 파일(다른 이름) 생성 금지
- 심각도는 아래 3개 문구만 허용:
  - `P1: 매우 심각 (릴리즈/머지 차단급, 즉시 수정)`
  - `P2: 보통 (중요하지만 단기 내 계획 수정 가능, 보통 다음 배포 전)`
  - `P3: 경미 (개선/리팩터링 성격, 후속 처리 가능)`

출력 파일(1개만):
- preflight의 `OUTPUT_FILE` 값
```

## 3) 통합 리뷰 (완전자동)

```text
아래 값을 자동 계산해서 최종 통합 리뷰를 작성하세요.

자동 계산 규칙:
1) BRANCH: `git branch --show-current`
2) BRANCH_SAFE: BRANCH에서 `/`를 `-`로 치환

입력:
- {REVIEWS_DIR}/base/
- {REVIEWS_DIR}/cross/

출력 템플릿:
- ./scripts/arena/templates/INTEGRATED_REVIEW_TEMPLATE.md

규칙:
- [A -> B] 근거 관계를 빠짐없이 표기
- 최종 이슈에 consensus 수치 기재
- must_fix_before_merge 명시
- 표는 요약용(`요약표`)으로만 사용
- 최종 판단 근거는 `상세` 섹션에 작성
- 이견 이슈는 반드시 상세 서술하고 아래를 모두 포함:
  - `최초제기_문제`(배경/발생_조건/실패_양상/근거_코드 포함)
  - `최초제안_조치`(즉시_조치/구조_개선/적용_조건/검증_계획 포함)
  - `연관_파일`
  - `재현_조건`
  - `상세_분석`
  - `영향_평가`
  - `필요후속조치`
- 심각도는 아래 3개 문구만 허용:
  - `P1: 매우 심각 (릴리즈/머지 차단급, 즉시 수정)`
  - `P2: 보통 (중요하지만 단기 내 계획 수정 가능, 보통 다음 배포 전)`
  - `P3: 경미 (개선/리팩터링 성격, 후속 처리 가능)`

출력 파일(1개만):
- {REVIEWS_DIR}/integrated/{BRANCH_SAFE}_integrated_review.md
```

## 운영 검증 (자동)

```text
bash ./scripts/arena/libexec/validate_review_artifacts.sh $(git branch --show-current) "{REVIEWS_DIR}"
```
