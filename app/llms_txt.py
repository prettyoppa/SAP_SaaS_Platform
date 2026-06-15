"""LLM/crawler-facing site summary (https://llmstxt.org/)."""

from __future__ import annotations

from .offer_inquiry_service import site_public_origin


def build_llms_txt(origin: str) -> str:
    base = (origin or "").rstrip("/")
    return f"""# SAP Development Partner (Catch Lab)

> Independent SaaS for SAP ABAP new development, analysis/improvement, and integration projects with AI agents and consultant matching.
> NOT affiliated with SAP SE, SAP Community official support, or learning.sap.com.
> Domain: sap.ireadschool.com — educational subdomain name only; this is a SAP developer workflow product, not a reading/school site.

## What this site is

- AI-assisted SAP development workflow: requirements interview → proposal → functional spec → delivery collaboration
- Consultant marketplace: request console, offers, matching, delivery workspace
- Public knowledge base with generalized SAP technical articles (no member request text or deliverable source code)

## Primary public URLs

- Home: {base}/
- About / product identity: {base}/about
- New ABAP development (RFP): {base}/services/abap
- Knowledge gallery (published articles): {base}/kb
- Notices: {base}/notices
- FAQ: {base}/faqs
- Terms: {base}/terms
- Privacy: {base}/privacy
- Sitemap: {base}/sitemap.xml

## What is NOT public (login required)

- Member request hubs: /abap-analysis, /integration (login for your request list)
- Member requests, interview transcripts, proposals, FS, delivered code, billing, admin

## Keywords

SAP ABAP, S/4HANA, ECC, RFP, functional specification, ALV, RFC, BAPI, IDoc, integration, Python SAP, VBA SAP, AI development assistant

## Operator

Catchy Lab — independent software vendor
"""


def llms_txt_for_request(request) -> str:
    return build_llms_txt(site_public_origin(request))
