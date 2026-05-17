"""홈 히어로 기본 HTML·사용 안내 동영상 (관리자 미설정 시)."""

from __future__ import annotations

# ABAP 코딩 튜토리얼 (관리자 URL 미입력 시 히어로 패널 기본 임베드)
DEFAULT_HOME_GUIDE_VIDEO_URL = "https://youtu.be/7lkdOdWdnS0"

DEFAULT_HOME_HERO_HTML = """<h1 class="hero-title">
  SAP 개발, Catchy가<br>함께 하겠습니다.<br>
  <span class="hero-power-agents text-gradient" data-i18n="hero.powerAgents">with 8 Power Agents</span>
</h1>
<p class="hero-sub">AI 에이전트가 요구사항을 분석하여 개발제안서를 생성합니다.</p>"""
