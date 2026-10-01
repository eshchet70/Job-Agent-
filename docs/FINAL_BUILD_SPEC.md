# Final Build Specification — Job Search Operating Agent

## Product objective
Build a human-in-the-loop job-search operating system that reduces low-value applications and increases the quality of qualified applications, resume terminology alignment, and human access to the hiring process.

## Non-negotiable design rules
1. Strategic Fit and ATS Readiness are separate scores.
2. Every material candidate claim must resolve to an Evidence Library ID.
3. Never fabricate experience, credentials, metrics, reporting relationships, email addresses, work authorization, or mutual connections.
4. Official company career/ATS source outranks aggregators for open/closed status.
5. People research distinguishes Confirmed / High / Medium / Low confidence.
6. External messages are drafted automatically but require explicit human approval before sending.
7. Authenticated accounts use interactive user login; never collect/store passwords or bypass MFA/CAPTCHA/security controls.
8. Excel is a human-facing tracker. SQLite is the MVP system of record.

## Target workflow
Discover -> Verify -> Deduplicate -> Hard Gates -> Strategic Fit -> ATS Match -> Evidence Map -> Hiring Management Chain -> Connection Analysis -> Personalized Outreach -> Human Approval -> Tracker -> MyGreenhouse Sync -> Learning.

## MVP screens
### 1. Analyze Job
Inputs: URL or pasted JD, company, title, location. Output: verification, hard gates, Strategic Fit, ATS, evidence map, pursuit decision.
### 2. People & Outreach
Output: hiring manager chain, sources/confidence, connection paths, recipient-specific message drafts, recommended sequence, approval controls.
### 3. Application Record
Output: tracker/database record, resume version, application status, next action/date, outreach history.
### 4. Sync
MyGreenhouse reconciliation: new records, status changes, conflicts. Authenticated access is optional and session-based.
### 5. Dashboard
Conversion by role family, pursuit tier, ATS readiness, human access, geography, channel and recipient type.

## Strategic Fit weights
- Functional Fit 25
- Seniority Fit 15
- Domain Fit 10
- Evidence Strength 15
- Location / Authorization 15
- Competitive Positioning 10
- Relationship Access 10

Tier 1 >= 80; Tier 2 70-79; Tier 3 60-69; Do Not Pursue <60. Hard gates override score until resolved.

## ATS scoring
- Critical keyword coverage 35%
- Important keyword coverage 20%
- Evidence coverage 25%
- Placement/prominence 10%
- Role/title/qualification alignment 10%

Keyword actions: KEEP, ADD, STRENGTHEN, DO_NOT_ADD. ADD requires supporting evidence.

## Hiring management chain
Research in this order: hiring manager, recruiter/talent partner, warm connector, hiring manager's manager, functional leader/peer, internal advocate. Store name, title, relationship to vacancy, source, checked date, confidence, connection path, priority, channel, message objective, draft, contacted date, response and next action.

## Outreach sequencing default
Day 0 apply; Day 0-1 warm introduction request if strong path exists; Day 1-2 recruiter; Day 2-4 hiring manager; Day 4-6 peer/advocate selectively; Day 7-10 one evidence-based follow-up; Day 18-21 reassess; Day 30 archive/ghost unless active evidence exists.

## Authenticated integration
Adapters must expose capability/state rather than assume login. Public mode always works. LinkedIn authenticated enrichment may add visible connection context when available. MyGreenhouse adapter may read portal-visible applications/statuses and create reconciliation proposals. Never silently overwrite conflicts.

## Definition of done
A single job can go from URL/JD to a persisted, auditable decision record with fit, ATS, evidence, people map, outreach drafts and tracker write-back. Tests cover formulas, unsupported-claim guardrails, hard gates, dedupe, source confidence and reconciliation conflicts.
