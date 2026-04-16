"""
Paid Tier Crew – SAP Dev Hub (구현 예정)

에이전트 구성:
  p_architect  (David)  – 상세 FS 작성
  p_coder      (Kevin)  – ABAP 코드 생성
  p_inspector  (Young)  – 코드 리뷰 및 수정 지시
  p_tester     (Brian)  – Unit Test 시나리오 작성
"""


def generate_fs_and_code(rfp_data: dict, proposal_text: str) -> dict:
    """
    Development Proposal을 바탕으로 상세 FS와 ABAP 코드를 생성합니다.
    (Phase 3 구현 예정)

    Returns:
        {
            "fs_text": str,
            "abap_code": str,
            "test_scenarios": list[str]
        }
    """
    raise NotImplementedError("Paid Tier 에이전트는 Phase 3에서 구현됩니다.")
