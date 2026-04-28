"""
seed_demo_data() — idempotent demo data for DCT Risk Intelligence Platform.
Called once on first startup when risks table is empty.
"""
import json
import sqlite3
from datetime import datetime, timedelta

from config import DB_PATH


def _risk_id_exists(cursor, risk_id):
    return cursor.execute("SELECT 1 FROM risks WHERE risk_id=?", (risk_id,)).fetchone() is not None


def seed_demo_data():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print(">> Checking demo data…")
    now = datetime.now()

    def dt(days_ago=0):
        return (now - timedelta(days=days_ago)).isoformat()

    # ── 5 Enterprise Risks ────────────────────────────────────────────────────
    enterprise = [
        ("ENT-001", "enterprise", "DCT Abu Dhabi", "Strategic",
         "Loss of Key Leadership During Critical Programme Delivery",
         "Departure of senior leadership during delivery of major cultural programmes could undermine continuity and stakeholder confidence.",
         "Succession planning in progress; deputy roles identified.", 3, 4, 12, "Open",  dt(45)),
        ("ENT-002", "enterprise", "DCT Abu Dhabi", "Financial",
         "Federal Budget Reduction Impacting Capital Projects",
         "Reduction in federal allocation for 2026 could delay planned infrastructure investments across museum and events portfolio.",
         "Contingency fund of AED 50M reserved; phased delivery plans drafted.", 3, 5, 15, "Open", dt(30)),
        ("ENT-003", "enterprise", "DCT Abu Dhabi", "Reputational",
         "International Media Scrutiny of Cultural Programme Standards",
         "Growing international media attention may amplify minor operational failures into reputational incidents.",
         "Media relations protocol updated; rapid response team established.", 2, 5, 10, "Open", dt(20)),
        ("ENT-004", "enterprise", "DCT Abu Dhabi", "Compliance & Regulatory",
         "Non-compliance with Updated Federal Data Protection Regulations",
         "New UAE PDPL requirements effective 2026 require significant updates to visitor data handling across all venues.",
         "Legal review commissioned; DPO appointed; 90-day remediation plan active.", 3, 4, 12, "Mitigating", dt(15)),
        ("ENT-005", "enterprise", "DCT Abu Dhabi", "Strategic",
         "Over-reliance on Single Technology Vendor for Core Systems",
         "Critical visitor management and ticketing infrastructure dependent on a single vendor creates systemic failure risk.",
         "RFP issued for secondary vendor; contract renegotiation in progress.", 2, 4, 8, "Open", dt(10)),
    ]

    # ── 8 Affiliate Risks ─────────────────────────────────────────────────────
    affiliate = [
        ("AFF-001", "affiliate", "Louvre Abu Dhabi", "Safety & Security",
         "Visitor Overcrowding During Peak Exhibition Periods",
         "Record visitor numbers during blockbuster exhibitions risk exceeding safe capacity thresholds.",
         "Dynamic ticketing cap of 4,500/day implemented; queue management upgraded.", 4, 4, 16, "Open", dt(40)),
        ("AFF-002", "affiliate", "Louvre Abu Dhabi", "Operational",
         "Art Logistics Delay — Incoming Loan from Louvre Paris",
         "Customs and logistics delays risk opening of the 'Mediterranean Civilisations' exhibition.",
         "Freight forwarder escalated; alternate opening schedule drafted.", 3, 4, 12, "Open", dt(35)),
        ("AFF-003", "affiliate", "Louvre Abu Dhabi", "Environmental & Health",
         "HVAC Failure Affecting Artwork Climate Control",
         "Ageing HVAC system in Gallery 9 presents risk of temperature excursion, damaging sensitive loans.",
         "Emergency replacement contract awarded; temporary portable units deployed.", 2, 5, 10, "Mitigating", dt(28)),
        ("AFF-004", "affiliate", "Zayed National Museum", "Financial",
         "Construction Delay Pushing Opening Beyond 2026 Target",
         "Supply chain disruptions and contractor performance issues risk delaying opening, impacting revenue forecasts.",
         "Weekly contractor review meetings; liquidated damages clauses invoked.", 3, 4, 12, "Open", dt(22)),
        ("AFF-005", "affiliate", "Zayed National Museum", "Compliance & Regulatory",
         "Artefact Provenance Documentation Incomplete for UNESCO Reporting",
         "24 artefacts lack full provenance chain required for UNESCO compliance reporting due Q1 2026.",
         "External provenance researcher engaged; 18 of 24 cases resolved.", 2, 4, 8, "Mitigating", dt(18)),
        ("AFF-006", "affiliate", "Abu Dhabi Events Dept", "Reputational",
         "Headline Artist Withdrawal from Major Cultural Festival",
         "Last-minute artist withdrawal from Abu Dhabi Classics Festival could damage brand and reduce ticket revenue.",
         "Contractual penalties in place; reserve artist roster maintained.", 3, 4, 12, "Open", dt(14)),
        ("AFF-007", "affiliate", "Abu Dhabi Events Dept", "Safety & Security",
         "Drone Activity Near Event Venues — Airspace Violation Risk",
         "Unauthorised drone activity near open-air events poses safety risk to crowds and performers.",
         "Drone detection equipment procured; coordination with Abu Dhabi Police active.", 3, 4, 12, "Open", dt(8)),
        ("AFF-008", "affiliate", "Abu Dhabi Events Dept", "Operational",
         "Ticket Platform Outage During High-Demand Sale Window",
         "Third-party ticketing platform experienced 4-hour outage during Formula E ticket release causing AED 2.1M in lost sales.",
         "SLA escalated; backup ticketing API integrated; load testing scheduled.", 4, 3, 12, "Mitigating", dt(5)),
    ]

    # ── 12 Department Risks ───────────────────────────────────────────────────
    department = [
        ("DEP-001", "department", "Events Operations", "Operational",
         "Insufficient Trained Crowd Stewards for Multi-Venue Weekend",
         "Events on 14–15 February require 850 trained stewards; current pool is 620.",
         "Emergency recruitment campaign; third-party stewarding firm contracted.", 4, 4, 16, "Open", dt(25)),
        ("DEP-002", "department", "Events Operations", "Safety & Security",
         "Medical Emergency Response Time Exceeds Target at Remote Stages",
         "Average EMS response time at perimeter stages is 8.2 minutes vs. 5-minute target.",
         "Two additional medical posts established; golf cart deployment approved.", 3, 4, 12, "Mitigating", dt(22)),
        ("DEP-003", "department", "Events Finance", "Financial",
         "FX Exposure on Euro-Denominated Artist Contracts",
         "EUR/AED rate movement of 5% would increase artist fee liability by AED 3.2M across Q2 2026 events.",
         "Forward FX contracts placed for 70% of exposure; hedge review monthly.", 3, 4, 12, "Open", dt(20)),
        ("DEP-004", "department", "Events Finance", "Financial",
         "Sponsorship Revenue Shortfall — 3 Major Deals Unsigned",
         "AED 18M in budgeted sponsorship revenue from 3 deals remains unsigned 60 days before financial year close.",
         "CEO-level outreach initiated; alternative sponsors identified.", 4, 4, 16, "Open", dt(18)),
        ("DEP-005", "department", "IT & Digital", "Operational",
         "Legacy CRM Migration Data Loss Risk",
         "Migration of 1.2M visitor records from legacy CRM carries risk of data corruption or loss.",
         "Full backup completed; migration dry run successful; rollback plan documented.", 2, 5, 10, "Mitigating", dt(16)),
        ("DEP-006", "department", "IT & Digital", "Compliance & Regulatory",
         "PDPL Consent Records Incomplete for Email Marketing Database",
         "Approximately 340,000 email subscribers lack valid consent records under new PDPL requirements.",
         "Re-consent campaign launched; non-consenting contacts suppressed.", 3, 4, 12, "Mitigating", dt(14)),
        ("DEP-007", "department", "Venues & Infrastructure", "Environmental & Health",
         "Extreme Heat Protocol — Outdoor Venue Cooling Capacity",
         "Summer events forecast 46°C+; cooling infrastructure at 3 outdoor venues assessed as insufficient.",
         "Temporary cooling towers ordered; event scheduling review for June–August.", 4, 4, 16, "Open", dt(12)),
        ("DEP-008", "department", "Venues & Infrastructure", "Operational",
         "Generator Fuel Reserves Below Minimum for 48-Hour Resilience",
         "Post-audit reveals generator fuel reserves at 2 venues cover only 18 hours vs. 48-hour resilience target.",
         "Emergency fuel order placed; storage capacity expansion approved.", 3, 4, 12, "Open", dt(10)),
        ("DEP-009", "department", "Marketing & Communications", "Reputational",
         "Negative Social Media Campaign Targeting Cultural Programme",
         "Coordinated social media criticism campaign has reached 2.4M impressions in 48 hours.",
         "Crisis comms agency engaged; factual correction content published.", 4, 3, 12, "Mitigating", dt(8)),
        ("DEP-010", "department", "Marketing & Communications", "Strategic",
         "Tourism KPI Target — Q2 2026 Visitor Arrivals 12% Below Trajectory",
         "Current Q2 arrival trajectory is 12% below target; risk of missing annual 15M visitor goal.",
         "Emergency marketing activation approved; airline partnership fast-tracked.", 3, 4, 12, "Open", dt(6)),
        ("DEP-011", "department", "Events Operations", "Compliance & Regulatory",
         "Events Permit Renewal Backlog — 5 Permits Expiring Before Events",
         "5 venue permits due for renewal expire before scheduled events; Abu Dhabi Municipality processing delays noted.",
         "Senior liaison assigned; 3 of 5 permits renewed; 2 escalated to Director level.", 3, 4, 12, "Mitigating", dt(4)),
        ("DEP-012", "department", "Events Finance", "Financial",
         "Contractor Payment Dispute — AED 4.2M Claim from AV Supplier",
         "Major AV contractor has filed a formal payment dispute for AED 4.2M, threatening withdrawal from upcoming events.",
         "Legal counsel engaged; interim payment of AED 1.8M agreed without prejudice.", 3, 4, 12, "Open", dt(2)),
    ]

    # ── 15 Event Risks — Abu Dhabi Film Festival 2025 ─────────────────────────
    event = [
        ("EVT-001", "event", "Abu Dhabi Film Festival 2025", "Safety & Security",
         "Crowd Surge at Opening Night Red Carpet",
         "Opening night expected 12,000 attendees in a 6,000-capacity street corridor; crush risk at entry pinch points.",
         "Crowd flow modelling completed; additional barriers ordered; police liaison confirmed.", 5, 5, 25, "Open", dt(30)),
        ("EVT-002", "event", "Abu Dhabi Film Festival 2025", "Operational",
         "Celebrity Security Detail Incompatible with UAE Protocol",
         "Three A-list attendees' private security teams do not hold UAE security licences; conflict with Abu Dhabi Police protocols.",
         "Police liaison working exemption agreements; briefings scheduled.", 3, 4, 12, "Mitigating", dt(28)),
        ("EVT-003", "event", "Abu Dhabi Film Festival 2025", "Reputational",
         "Controversial Film Screening — Potential Public Backlash",
         "Two selected films contain content that may generate public controversy; risk of social media amplification.",
         "Media affairs review completed; Q&A panel format adjusted; communications brief drafted.", 3, 4, 12, "Open", dt(26)),
        ("EVT-004", "event", "Abu Dhabi Film Festival 2025", "Financial",
         "Headline Sponsor Withdrawal — 45 Days Before Opening",
         "Primary sponsor has indicated potential withdrawal due to internal restructuring; AED 8M revenue at risk.",
         "Alternative sponsors approached; emergency board meeting called.", 4, 5, 20, "Open", dt(24)),
        ("EVT-005", "event", "Abu Dhabi Film Festival 2025", "Operational",
         "Projection System Failure — 4K Laser Projectors Not Certified",
         "Venue projection systems require recertification for DCI 4K; certification delayed by supplier.",
         "Backup 2K systems on standby; supplier escalated; target certification date confirmed.", 3, 4, 12, "Mitigating", dt(22)),
        ("EVT-006", "event", "Abu Dhabi Film Festival 2025", "Compliance & Regulatory",
         "Film Copyright Clearance — 3 International Titles Unresolved",
         "3 international films lack complete UAE distribution rights; potential last-minute programme changes.",
         "Legal team in negotiation; alternate titles on reserve programme.", 4, 3, 12, "Open", dt(20)),
        ("EVT-007", "event", "Abu Dhabi Film Festival 2025", "Environmental & Health",
         "Outdoor Screening Venue — Sandstorm Warning During Opening Weekend",
         "Meteorological forecast indicates 60% probability of sandstorm during opening outdoor screening.",
         "Covered contingency venue identified; automated weather monitoring active.", 4, 3, 12, "Open", dt(18)),
        ("EVT-008", "event", "Abu Dhabi Film Festival 2025", "Safety & Security",
         "Protest Activity Near Festival Venue — Intelligence Advisory",
         "Abu Dhabi Police intelligence advisory received regarding potential protest activity near main venue.",
         "Additional plainclothes officers deployed; entry screening enhanced.", 3, 4, 12, "Mitigating", dt(16)),
        ("EVT-009", "event", "Abu Dhabi Film Festival 2025", "Operational",
         "Interpreter Shortage for Simultaneous Translation — 7 Languages",
         "Festival requires simultaneous translation in 7 languages; confirmed interpreters available for 5.",
         "Remote interpretation service contracted as backup; AI captioning activated.", 2, 3, 6, "Mitigating", dt(14)),
        ("EVT-010", "event", "Abu Dhabi Film Festival 2025", "Financial",
         "Ticket Fraud — 800 Counterfeit Tickets Identified Pre-Event",
         "Forensic ticket analysis identified approximately 800 counterfeit tickets in circulation.",
         "NFC-enabled replacement tickets issued; coordination with cybercrime unit active.", 3, 4, 12, "Mitigating", dt(12)),
        ("EVT-011", "event", "Abu Dhabi Film Festival 2025", "Reputational",
         "Jury Member Social Media Controversy",
         "International jury member posted polarising social media content; media enquiries received.",
         "PR team monitoring; jury member briefed on media obligations; holding statement prepared.", 3, 3, 9, "Open", dt(10)),
        ("EVT-012", "event", "Abu Dhabi Film Festival 2025", "Operational",
         "Catering Contractor Failure — Food Safety Inspection Failed",
         "Primary catering contractor failed municipal food safety inspection; 72-hour closure notice issued.",
         "Secondary contractor activated; municipality re-inspection scheduled.", 4, 4, 16, "Mitigating", dt(8)),
        ("EVT-013", "event", "Abu Dhabi Film Festival 2025", "Compliance & Regulatory",
         "GDPR Data Transfer — EU Filmmaker Personal Data Handling",
         "EU filmmakers' personal data processed in UAE without adequate transfer mechanism under GDPR.",
         "Standard Contractual Clauses drafted; DPO review in progress.", 2, 3, 6, "Open", dt(6)),
        ("EVT-014", "event", "Abu Dhabi Film Festival 2025", "Safety & Security",
         "Medical Emergency Capacity — Peak Night Attendance",
         "Peak night attendance of 15,000 exceeds current on-site medical coverage ratio (1:500 target).",
         "Additional paramedic teams contracted; field hospital capacity confirmed.", 3, 4, 12, "Open", dt(4)),
        ("EVT-015", "event", "Abu Dhabi Film Festival 2025", "Strategic",
         "Competing International Festival Overlap — Venice Extension",
         "Venice Film Festival announced 2-day extension overlapping with ADFF opening; key talent double-booked.",
         "Talent scheduling reviewed; 3 confirmed commitments renegotiated successfully.", 2, 3, 6, "Accepted", dt(2)),
    ]

    # Insert risks only if their risk_id does not already exist
    inserted = 0
    for risks_list in [enterprise, affiliate, department, event]:
        for r in risks_list:
            rid, level, entity, cat, title, desc, mit, lh, imp, score, status, created = r
            if _risk_id_exists(c, rid):
                continue
            c.execute("""
                INSERT INTO risks
                  (risk_id, level, entity_name, category, title, description,
                   mitigation, likelihood, impact, risk_score, status,
                   source, owner, created_date, updated_date, velocity)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (rid, level, entity, cat, title, desc, mit, lh, imp, score,
                  status, "Demo", "Risk Management Office", created, created,
                  "Short-term"))
            inserted += 1
    if inserted:
        print(f">> Seeded {inserted} demo risks")

    # ── 3 Ingested Documents ──────────────────────────────────────────────────
    import os
    from config import UPLOAD_FOLDER
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    docs = [
        ("ADFF_2025_Risk_Register.txt",   "risk_register",   10,
         "Abu Dhabi Film Festival 2025 risk register with 10 identified risks across safety, operational and financial categories."),
        ("DCT_Lessons_Learned_2024.txt",   "lesson_learned",  8,
         "Post-event lessons learned from 2024 DCT events programme covering crowd management, logistics and stakeholder coordination."),
        ("Events_Compliance_Checklist.txt","checklist",        0,
         "Municipal compliance checklist for large events in Abu Dhabi including permit requirements, safety standards and insurance thresholds."),
    ]
    for fname, dtype, risk_count, summary in docs:
        fpath = os.path.join(UPLOAD_FOLDER, fname)
        if not os.path.exists(fpath):
            with open(fpath, "w") as f:
                f.write(f"# {fname}\n\nDemo seed file for DCT Risk Intelligence Platform.\n{summary}\n")
        exists = c.execute(
            "SELECT 1 FROM ingested_documents WHERE filename=?", (fname,)
        ).fetchone()
        if not exists:
            c.execute("""
                INSERT INTO ingested_documents
                  (filename, doc_type, upload_date, processed, extracted_risks_count, summary)
                VALUES (?,?,datetime('now'),1,?,?)
            """, (fname, dtype, risk_count, summary))

    # ── 8 News Items ──────────────────────────────────────────────────────────
    news = [
        ("UAE issues Level 2 heat advisory — 46°C forecast for Abu Dhabi",
         "WAM", "https://wam.ae", 9,
         '["Safety & Security","Operational","Environmental & Health"]',
         "Extreme heat directly threatens outdoor DCT events; cooling infrastructure and scheduling must be reviewed immediately.",
         (now - timedelta(hours=4)).isoformat()),
        ("Abu Dhabi Police release updated crowd management guidelines for events >10,000",
         "Gulf News", "https://gulfnews.com", 9,
         '["Safety & Security","Compliance & Regulatory"]',
         "New police requirements for security plan resubmission affect all large DCT events scheduled in Q2–Q3 2026.",
         (now - timedelta(hours=8)).isoformat()),
        ("Ransomware attack targets ticketing platform at UAE entertainment venue",
         "Arabian Business", "https://arabianbusiness.com", 8,
         '["Operational","Financial","Reputational"]',
         "Attack on regional ticketing system highlights cyber vulnerability of DCT's own platform ahead of peak season.",
         (now - timedelta(hours=14)).isoformat()),
        ("Severe shamal dust storm forecast Thursday–Friday, Abu Dhabi",
         "The National", "https://thenationalnews.com", 8,
         '["Environmental & Health","Operational"]',
         "Dust storm with <500m visibility poses direct threat to outdoor DCT events and venue operations this week.",
         (now - timedelta(hours=2)).isoformat()),
        ("Ministry of Economy tightens event contractor licensing — Q2 2026",
         "Khaleej Times", "https://khaleejtimes.com", 7,
         '["Compliance & Regulatory","Financial"]',
         "New licensing rules require all event contractors over AED 500K to requalify; DCT vendor register needs audit.",
         (now - timedelta(hours=24)).isoformat()),
        ("Abu Dhabi records 14% surge in Q1 2026 international tourist arrivals",
         "WAM", "https://wam.ae", 6,
         '["Strategic","Operational"]',
         "Record arrivals at 91% hotel occupancy increase crowd pressure on DCT venues and events infrastructure.",
         (now - timedelta(hours=36)).isoformat()),
        ("Regional geopolitical tensions — UAE security posture elevated",
         "Reuters", "https://reuters.com", 8,
         '["Safety & Security","Strategic"]',
         "Elevated threat posture requires enhanced screening and security coordination for all large DCT public gatherings.",
         (now - timedelta(hours=10)).isoformat()),
        ("Etihad Airways cancels 12 flights — passenger disruption expected",
         "The National", "https://thenationalnews.com", 6,
         '["Operational","Reputational"]',
         "Flight cancellations may affect international artist and VIP arrivals for upcoming DCT events.",
         (now - timedelta(hours=6)).isoformat()),
    ]
    for headline, source, url, score, cats, insight, pub_date in news:
        c.execute("""
            INSERT OR IGNORE INTO news_items
              (headline, source, url, published_date, fetched_date,
               relevance_score, mapped_risk_categories, ai_analysis)
            VALUES (?,?,?,?,datetime('now'),?,?,?)
        """, (headline, source, url, pub_date, score, cats, insight))

    # ── 1 Completed ARC Pack (Q4 2025) ───────────────────────────────────────
    arc_content = {
        "period": "Q4 2025",
        "title":  "DCT ARC Pack – Q4 2025",
        "summary": {"total": 40, "high": 12, "medium": 22, "low": 6},
        "by_level":  {"enterprise": 5, "affiliate": 8, "department": 12, "event": 15},
        "by_status": {"Open": 28, "Mitigating": 9, "Accepted": 2, "Closed": 1},
        "narrative": (
            "Q4 2025 risk posture reflects an organisation managing significant growth-related pressures. "
            "The portfolio of 40 active risks includes 12 rated High, driven primarily by capacity and "
            "compliance themes. Key mitigations progressed well during the quarter, with the Louvre Abu Dhabi "
            "HVAC replacement completed and the PDPL re-consent campaign on track. The committee's attention "
            "is drawn to the financial exposure from unsigned sponsorship agreements and the ongoing contractor "
            "dispute, both of which require resolution before Q1 2026 planning closes."
        ),
        "top_risks": [
            {"risk_id": "EVT-001", "title": "Crowd Surge at Opening Night Red Carpet",
             "level": "event", "score": 25, "level_label": "High", "status": "Open", "owner": "Risk Management Office"},
            {"risk_id": "ENT-002", "title": "Federal Budget Reduction Impacting Capital Projects",
             "level": "enterprise", "score": 15, "level_label": "High", "status": "Open", "owner": "Risk Management Office"},
        ],
    }
    arc_exists = c.execute(
        "SELECT 1 FROM arc_packs WHERE period='Q4 2025'"
    ).fetchone()
    if not arc_exists:
        c.execute("""
            INSERT INTO arc_packs (title, period, generated_date, generated_by, status, content_json)
            VALUES (?,?,?,?,?,?)
        """, (
            "DCT ARC Pack – Q4 2025", "Q4 2025",
            (now - timedelta(days=14)).isoformat(),
            "Risk Management Office", "Approved",
            json.dumps(arc_content)
        ))

    conn.commit()
    conn.close()
    print(f">> Demo data seeded: {len(enterprise)} enterprise, {len(affiliate)} affiliate, "
          f"{len(department)} department, {len(event)} event risks; "
          f"3 docs, 8 news items, 1 ARC pack.")
