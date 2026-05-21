# SAP Development Partner — User Guide (Draft)

**Version:** 2026-05 (for review)  
**Operator:** Catchy Lab

This guide describes features as currently implemented. Limits and fees follow your subscription plan and admin notices.


## 1. Overview

SAP Development Partner is a hub for **new ABAP development (RFP)**, **analysis/improvement**, and **integration** requests. AI agents help with **interview → Development Proposal**. Consultant members may provide **offers**, **matching**, **functional specs (FS)**, **delivered code**, and **final as-built deliverables**.

- **Free / low cost:** Request creation, AI interview, proposal (per plan and AI credits)
- **Paid / quotas:** FS, dev code, regenerations, offers
- **Language:** Use the header **KO / EN** toggle (some admin content is stored in both languages)


## 2. Getting started

### 2.1 Sign up and login

1. **Sign up** with email, password, name; agree to Terms and Privacy Policy
2. **Email verification** via link (if enabled)
3. **Phone verification** when required for profile, alerts, or trial
4. **Login** from the top menu; password recovery available

### 2.2 Experience trial

- New accounts may receive an **Experience trial** (e.g. once per email/phone).
- During trial, some paid-tier limits may match Junior-level entitlements.

### 2.3 AI credits

- AI interview, proposal, FS, code, and AI inquiry chat may **consume AI credits** (KRW balance).
- Open **Usage & balance** to see balance, **submit bank-transfer top-up**, cancel pending claims, and view history.
- Balance updates after deposit confirmation (admin process).


## 3. Home page

| Area | Description |
|------|-------------|
| **Hero (left)** | Title, subcopy, description (admin-configured) |
| **Getting started (right)** | Admin **guide text** (character typing) → else **YouTube embed** → else **ABAP typing demo** |
| **Details** | User guide PDF (default `/static/docs/user-guide.pdf` or custom URL) |
| **Row 1 tiles** | Notices · FAQ · Inquiry/Review — full list pages |
| **Row 2 tiles** | New development · Analysis · Integration |
| **When logged in** | Counts on tiles (totals, delivery, proposal, analysis, in progress, drafts) |

Admins edit copy via **Home tile editor** (bottom of home) or **Admin → Site settings**.


## 4. New development (RFP)

### 4.1 Create a request

1. **New development** tile or **RFP** menu → wizard
2. Select up to **3 SAP modules** and **3 development types**
3. Enter **requirements** (plain/rich text, screenshots)
4. Attach files and **reference ABAP** (program/section structure)
5. **Save draft** or **submit**

### 4.2 AI interview

- After submit, **AI interview** (up to 3 rounds, limited questions per round)
- Answers advance rounds or trigger **proposal generation**
- **Code gallery** matches may improve questions

### 4.3 Development Proposal

- AI generates a **Development Proposal** draft
- View/print (PDF) on hub **Proposal** tab; **regenerate** per plan/credits

### 4.4 Request hub phases

| Phase | Content |
|-------|---------|
| **Request** | Submitted body, attachments, reference code |
| **Interview** | Q&A history |
| **Proposal** | Proposal text |
| **FS** | Functional spec (paid / policy) |
| **Dev code** | Delivered ABAP |
| **As-built deliverable** | Single file upload (ZIP recommended); reusable as reference on later requests |

### 4.5 Offers, matching, inquiries

- **Offers** panel on proposal (and related) views
- Requester: **match** or **cancel match** (may be blocked after deliverables)
- Consultant: submit/withdraw offers; **inquiry/reply** (email/SMS consent shown; consultant email hidden)
- **AI inquiry** float (bottom-right, uses credits)

### 4.6 Dashboard

- List/filter/sort your RFPs; open hub via phase shortcuts


## 5. ABAP analysis / improvement

1. **Analysis** tile → submit requirements, ABAP, attachments
2. View **analysis results** by program and section tabs
3. Hub phases: request, analysis, proposal, etc., similar to RFP where enabled
4. Interview, offers, as-built, and AI chat follow the same patterns when available


## 6. Integration development

1. **Integration** tile → VBA, API, batch, Python, etc.
2. Reference ABAP shown in program/section structure
3. Same hub pattern: interview → proposal → FS → code → as-built → offers


## 7. Code gallery

- Menu **Code gallery**: search and view admin-published ABAP examples
- Use as reference when drafting requests


## 8. Notices, FAQ, inquiry/review

- Dedicated **notice** and **FAQ** list/detail pages (Markdown titles/bodies; EN fields may exist)
- **Inquiry/review:** post, comment, star ratings; privacy and admin suppression rules apply
- Home tabs show previews; use full list pages for browsing


## 9. Consultant members

### 9.1 Registration

- Choose **consultant** at sign-up; upload profile attachment; await approval

### 9.2 Request console

- **Request console:** browse other members’ requests (per policy/scope)
- Submit offers and handle inquiries

### 9.3 Consultant plans

- Experience, Junior, Senior, Superior — different quotas for offers, FS, code (see plan page)


## 10. Member subscription plans

- Experience, End User, Power User, Process Innovator, etc.
- Feature matrix: inquiries/reviews, dev requests, proposal regen, FS, code, etc.
- Plan changes per operations (bank transfer, admin grant)


## 11. Profile and account

- Profile: name, company, timezone, password, email change (verification), phone, notification consent
- Switch to consultant from profile
- **Delete account:** grace period; cancel via email link during grace


## 12. UI tips

- **Dark/light theme**
- **Processing** overlay on long operations
- **Draft** float on compose screens (stacked above AI inquiry when both present)
- Top-up FAB may hide on hub/detail where AI inquiry float is shown


## 13. Admin (reference)

- Site settings: home copy, guide text KO/EN, video URL, tips, service intros, terms, privacy
- Notices, FAQ, review moderation, plans, payment confirmation, gallery/KB — separate admin menus


## 14. Contact

Support, billing, privacy: 〔insert contact〕

---

*Draft only; the live site and notices prevail.*
