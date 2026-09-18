# 골목 통행가능폭 산출 — 위성영상 AI + 국가공간정보

대전 소방차 진입곤란 지정 26개소 37조각에 대해
`통행가능폭 = 도로 폭 − 점유 변수의 횡방향 폭` 을 산출한 연구의 재현 자료.

## 이 저장소를 내려받은 사람이 어디까지 확인할 수 있는가 (2026-09-18 감사 기준)

| 단계 | 준비 | 확인할 수 있는 것 | 확인할 수 없는 것 |
|---|---|---|---|
| ① 설치 없이(표준 라이브러리) | `git clone` 만 | `verify_deliverables.py` — 제출본 수치 38개를 `deliverables/` CSV 에서 재계산(통과 38) · `verify_numbers.py` — 본문 추출본 vs 산출물 · `slot_time_stage1.py` — 시간 축 1단계(바이트 일치) · `PREREG.md` 의 blob SHA-1 대조 | 산출물이 「맞게 만들어졌는가」 |
| ② `pip install -r requirements.txt` 후(인터넷·키 없이) | Python 3.11+ · 패키지 | 커밋된 원시 캐시(`raw/*.jsonl.gz`)와 마스크 캐시(`derived/sam_vehicle_cache/`)에서 **전국 집계·민감도·개소 집계·AI-A·교차표·CCTV 대조**를 재실행 → 산출물과 대조(2026-09-18 전부 동일) | 브이월드 조회가 필요한 것(내접폭·경사·연계 테이블·레이어 커버리지) · 표준노드링크가 필요한 것(포함률·위계 대조) · SAM 재실행 |
| ③ 원천을 직접 받은 뒤(브이월드 키 · 표준노드링크 612 MB · SAM 가중치 358 MB) | 위 + `VWORLD_APIKEY`·`VWORLD_DOMAIN` · `acquire_open.py nodelink` · SAM 가중치 | 나머지 전부 — 브이월드 조회 계열 · 표준노드링크 계열 · **SAM 사슬(원 마스크 3,838 → 71)** 재실행 | 손으로 만든 표 5종(`산출물_명세.md` 「생성 스크립트 없음」) · 제출본 `.hwpx` 기반 산출(`주장_출처대조.csv` 190행판 · `조판편차_실측.json`) · 비공개 코어 모듈이 필요한 이태원 슬롯 시연(`slot_itaewon_*.py`) |

무엇이 실제로 돌았고 무엇이 안 돌았는지는 **`docs/재현성_감사_2026-09-18.md`**(실행 표 · 교체한 산출물 · 여전히 안 되는 것 · 판정)와
`docs/재현로그_2026-09-18.md` 에 있다. 이 README 의 명령은 2026-09-18 에 한 번씩 실제로 실행했다 — 단 `acquire_open.py nodelink`(271 MB 다운로드)와 SAM 가중치 다운로드는 돌리지 않았고(이미 있는 파일을 연결해 썼다), `pip install` 은 새 venv 에서 torch 를 뺀 핀 그대로 설치 + torch 는 `--dry-run` 으로 확인했다.

## 방법
1. 브이월드 WMTS Satellite z19(GSD 0.2406 m/px @ 위도 36.3225)에서 작업창 생성
2. SAM ViT-B(Apache-2.0) 사전학습 가중치를 **조정 없이** 로컬 CPU 에서 구동 → 원 마스크 3,838
3. 차량 규격 선험 통과 709 · 도로명주소 도로구간 버퍼(road_bt/2) 안 351
4. 둘 다 통과한 차량 후보 71 (규격 통과분의 90.0 %가 버퍼 밖으로 제외)
5. 횡점유를 도로 폭에서 차감 → `min(도로경계 면 차감폭, W_worst)` 을 최종 채택(fail-closed)

## 판정 규칙
`docs/판정기준.md` — §29 폭 축 밴드 · §34 SAM·버퍼·산식 · §35 대중교통 유입.
**판정 규칙은 산출 실행 전에 확정·기록했으며 결과를 본 뒤 바꾸지 않았다** — 라고 작성자는 기록한다.
각 절 머리에 사전 확정 표기가 있다. 문서 안의 D-### 는 판정 기준을 사전 확정한 작업 순번이다.
**제3자가 검증할 수 있는 범위는 `PREREG.md` 첫머리에 적었다**(커밋 시각은 검증 불가 · 본문 blob SHA-1 만 대조 가능).

## ① 바로 확인하기 (설치·원천 데이터·인터넷 불필요)

```bash
python scripts/verify_deliverables.py
```
`deliverables/` 의 CSV 만 읽어 제출본이 주장하는 수치 **38개를 다시 계산**한다 —
SAM 사슬(3,838 · 709 · 351 · 71 · 90.0 %) · 폭 산식 37조각 전수 · 밴드 임계 ·
AI 차감이 판정을 낮춘 7조각과 전이 내역 · 최종값을 결정한 21조각 · 내접폭 33/4 ·
사람 대조 9/5 · 민감도 86.5~100 %·89.2 % · 전국 78.2 % · 26↔37 구조 · 파일 간 키 일치.
하나라도 어긋나면 종료 코드 1.

```bash
python scripts/verify_numbers.py docs/서식2_본문_2026-09-18.txt .
```
제출본 서식2 본문(저장소에 넣은 텍스트 추출본)의 수치를 `data/vworld/national/derived/sam_vehicle_width.json` ·
`deliverables/*.csv` 와 대조한다. 인자 두 개(본문 `.txt` 또는 `.hwpx` · 저장소 루트)가 **필수**다 — 인자 없이 돌리면 `IndexError` 로 죽는다.
`PASS` 가 나와야 한다.

```bash
python scripts/slot_time_stage1.py
```
시간 축 1단계. **속도를 가정하지 않는다.** 법정 값만 쓴다 — 보행 1.0 m/s(도로교통법 시행규칙 보행신호 산정) ·
E 2.5 m(KFS 0008 3.3) · P 1.2 m(편의증진법 별표1) · G 2.0 m(도로구조규칙 제5조).
산출: `deliverables/슬롯시간_26개소.csv`(37행 · 입력 결측 2조각은 사유와 함께 남긴다).

```bash
for f in docs/prereg/*_판정기준.md; do echo "$(git hash-object "$f")  $f"; done
```
`PREREG.md` 표의 blob SHA-1 열과 같아야 한다(10/10).

## ② 패키지 설치 후 (인터넷·키 불필요 — 커밋된 캐시로 재실행)

```bash
pip install -r requirements.txt
```
Python 3.11 이상(원 실행 3.13). torch·segment-anything 은 SAM 단계에서만 필요하다(`requirements.txt` 주석).

```bash
python scripts/road_bt_national.py agg          # 전국 875,892구간 · 시도 16 집계 → derived/road_bt_national.json
python scripts/road_bt_crosstab_export.py       # → deliverables/전국폭속성교차표_A_요약.csv · _B_값구간.csv
python scripts/sensitivity.py                   # 마스크 캐시로 민감도 → deliverables/민감도_버퍼폭.csv · 민감도_규격선험.csv
python scripts/sensitivity_boundary.py          # → deliverables/민감도_경계값10건.csv
python scripts/site_table_26.py                 # → deliverables/26개소_산출표.csv · .md
python scripts/water_slot_buildings.py          # → deliverables/용수도달성·슬롯순서·접한건물수_26개소.csv (raw/firewater/*.csv.gz 사용)
python scripts/ai_a_classifier.py run           # → deliverables/AI-A_모델유사골목_상위.csv (raw/daejeon_sprd_geom.jsonl.gz 사용)
python scripts/daejeon_cctv_match.py            # → deliverables/대전_단속CCTV_골목급대조.csv
python scripts/ngii_five_way.py                 # → deliverables/AI-C_도로경계내접폭_5자대조.csv
python scripts/transit_inflow.py                # 반경 100 m 정류장·역사(위치)
python scripts/transit_inflow_volume.py         # 그 지점의 승하차 인원 → deliverables/대중교통유입규모_26개소.csv
python scripts/audit_claims.py docs/서식2_본문_2026-09-18.txt . deliverables/주장_출처대조_사람판정.csv   # → deliverables/주장_출처대조.csv 를 덮어쓴다(216행 · 커밋본 190행은 .hwpx 입력 — 산출물_명세 참조)
```
원시 캐시는 `data/vworld/national/raw/*.jsonl.gz` 로 커밋돼 있다(평문 `.jsonl` 이 없으면 `scripts/_rawio.py` 가 `.gz` 를 연다).
대중교통은 도시철도 시간대별(공공데이터포털 15060591) · 버스 일 단위(대전교통 빅데이터 플랫폼)이며 **버스에 도시철도 시간대 비율을 옮기지 않았다.**

## ③ 원천을 직접 받은 뒤

### 브이월드 인증키 — 환경변수로만
```powershell
$env:VWORLD_APIKEY = '<브이월드 개발키>'      # 저장소·로그에 남기지 않는다. 앞뒤 공백은 스크립트가 걷어낸다
$env:VWORLD_DOMAIN = 'localhost'             # 키 발급 시 등록한 도메인. 없으면 모든 요청이 ServiceExceptionReport 로 실패한다(2026-09-18 실측)
```
```bash
python scripts/vworld_layer_probe_26.py   # 16개 레이어 × 37조각 → deliverables/브이월드_레이어_커버리지_26개소.csv
python scripts/ngii_medial_width.py       # 도로경계 면 내접폭 → deliverables/도로경계내접폭_26개소.csv
python scripts/slope_26.py                # 경사 → deliverables/경사_26개소.csv (사실상 전 행 미산출 — 산출물_명세 참조)
python scripts/missing_alley_crosscheck.py
python scripts/access37_geocode.py --v2
python scripts/vworld_api_probe.py        # API 동작 기록(시점 의존 — 커밋본은 2026-09-15 기록)
```
브이월드 레이어 조회는 **조회했고 0건**과 **조회하지 못함**을 끝까지 분리해 기록한다 — 미조회를 「없다」로 쓰지 않기 위해서다.
2026-09-18 실행(실패 0건): 정밀도로지도 차도구간·주차면·높이장애물·과속방지턱은 37조각 전부 0건.

### 표준노드링크 (국가교통정보센터 · 612 MB · 저장소에 없음)
```bash
python scripts/acquire_open.py nodelink   # → data/vworld/national/raw/NODELINKDATA_20260914/MOCT_LINK.shp (판: 2026-09-14)
python scripts/national_inclusion.py agg      # → deliverables/전국대조군_길번길포함률.csv
python scripts/hierarchy_compare.py           # → deliverables/도로명위계_전국대조.csv (수기 주석 행 1줄은 나오지 않는다)
python scripts/hierarchy_compare_v2.py agg    # → deliverables/도로명위계_전국대조_길이.csv
python scripts/inclusion_rate.py              # → deliverables/이름포함률_대전.csv (브이월드 키도 필요)
python scripts/linkage_table.py               # → derived/linkage_table.csv (브이월드 키도 필요)
python scripts/turn_geometry_census.py        # 전국 회전 기하 전수 → derived/turn_census.json (16 GB PC 에서 109 s · 7 GB 여유일 때 완주)
```
`acquire_open.py` 를 **인자 없이** 돌리면 6개 원본을 전부 내려받는다.

### SAM 가중치 (Apache-2.0 · 358 MB · 저장소에 없음)
```bash
pip install torch==2.14.0 torchvision==0.29.0 --index-url https://download.pytorch.org/whl/cpu
pip install "segment-anything @ git+https://github.com/facebookresearch/segment-anything.git"
# https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth → data/vworld/models/sam_vit_b_01ec64.pth
python scripts/sam_vehicle_width.py       # 37조각 · CPU 조각당 약 130 s(마스크) + 120 s(검증창) — 마스크 캐시가 있으면 SAM 을 건너뛴다
python scripts/determinism_check.py       # 변정7길 한 조각 재실행 일치 확인
```
`derived/sam_vehicle_cache/` 에 마스크 캐시가 커밋돼 있으므로, **SAM 을 실제로 다시 돌리려면 그 폴더를 치우고** 실행한다.
2026-09-18 이 PC 에서 캐시를 치우고 처음부터 돌린 결과(100 분): 원 마스크 3,838 · 규격 통과 709 · 회랑 안 351 · 차량 후보 71 — **커밋본과 바이트 단위로 같고, 마스크 캐시 48개 파일도 전부 같았다.**
정사영상 타일은 `data/vworld/ortho_cache/` 에 두며 이용조건상 재배포하지 않는다(없으면 키로 자동 수급).

## 검증 결과
- **민감도** — 버퍼 폭 0.8~1.2배에서 폭 판정 불변율 86.5~100 %. 규격 선험 항목별 ±10 %에서 89.2 % 이상 유지
- **결정성** — 변정7길 동일 입력 재실행 시 마스크 93개 · 차량 후보 5대가 행 단위로 일치(원 실행 기록 · 2026-09-18 재확인은 감사 문서 참조)
- **사람 대조** — 9조각 예비 대조에서 대수 일치 5. 정확도 주장이 아니다

## 한계
- 위성영상 촬영 시점이 타일에 표기되지 않아 실시간이 아니다(증거 등급 C). 「해당 촬영 시점 추정」이다
- 통과 임계 3.5 m 와 차량 규격 선험은 본 연구가 정한 가정이다. 그래서 **통과를 확정하지 않고 배제·보류만 판정**한다
- 용수 도달성은 호스 연장 기준 미확보로 26개소 전부 UNKNOWN 이다
- 시간 슬롯의 시각 계산과 집행 층은 구현하지 않았다(설계)
- `deliverables/` 중 5종(방범CCTV · ITS영상CCTV · 주정차허용 · 보행약자축 · 차종투입판정)은 손으로 만든 표라 스크립트로 재현되지 않는다(`산출물_명세.md`)

## 데이터 출처
전부 공개·무상. 브이월드 WMTS/WFS · 도로명주소 도로구간 · 연속수치지형도 · 표준노드링크 ·
공공데이터포털 표준데이터. 상용 지도·경로·비전·언어 모델 API 0건.

## 저자
김영민 · 정병진

## 라이선스
코드 MIT. SAM 가중치는 Apache-2.0 이며 이 저장소에 포함하지 않는다.
