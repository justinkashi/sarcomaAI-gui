# SarcomaAI GUI — Product Status & Forward Plan
**Forward Deployed Engineering Report**
Date: May 2026 | Author: Justin Kashi
Audience: Team leads, clinical partners, institutional stakeholders

---

## What This Document Is

This document gives an honest picture of where the SarcomaAI application stands today — what is working well, what is quietly dangerous, and what we are proposing to do about it and in what order. It is written for a non-technical audience. Nothing here requires engineering background to understand.

---

## What the Application Does Today

SarcomaAI GUI is the tool that a hospital uses to contribute patient data to the federated learning project. A research coordinator or radiologist at a participating institution:

1. Opens the app on a clinical workstation
2. Browses through MRI scans from their PACS system
3. Labels each scan as T1 or T2 using the visual viewer
4. Clicks "Run Pipeline" — the app anonymizes the data and converts it into the format the AI model needs
5. The processed data stays on-premise at the institution, ready for federated training

The application is functional and has been used successfully at MUHC and MSKCC. The core workflow works. The issues described below are not reasons the app is failing today — they are reasons it could fail tomorrow, or reasons it will struggle to scale to new institutions.

---

## Section 1 — The Dangerous Issues

These are issues where the consequence of inaction is severe, not just inconvenient.

---

### 1.1 The Anonymization Gap

**What it is:**
When the pipeline runs, it strips patient-identifying information from the DICOM files — names, dates, MRN numbers, physician names. This is mandatory under both Canadian (PIPEDA) and US (HIPAA) privacy law, and is a condition of our ethics board approval.

The problem is that the stripping process only looks for information stored in standard, well-known locations in the DICOM file. Medical imaging systems (PACS) from different vendors — Philips, Siemens, GE, IntelePACS — also store information in non-standard, vendor-specific locations. The pipeline does not look there. Additionally, some scanner types literally print the patient name directly onto a preview image as white text on the scan itself. Stripping the metadata has no effect on text embedded in the image pixels.

There is also currently no verification step. Once the pipeline finishes, it marks the patient as anonymized and moves on. Nobody checks whether the anonymization actually succeeded.

**Why this matters:**
If a file containing a patient name enters the STS dataset labeled as anonymized, and that file is later accessed, audited, or shared as part of the federated project, this is a privacy breach under both PIPEDA and HIPAA. It must be reported to the ethics board. Depending on severity, this can result in suspension of the study, revocation of REB approval, and mandatory notification of affected patients. This is the highest-stakes risk the project currently carries.

**What we are proposing:**
After the pipeline runs, automatically re-read every processed file and confirm that every sensitive field now contains a dummy value. Log the result. Flag anything suspicious for human review before marking the patient as complete. Add the ability for each institution to specify additional fields that are specific to their system. This is not a major engineering undertaking — it is a verification step that should have been there from the start.

---

### 1.2 The Ledger

**What it is:**
The pipeline assigns each patient a coded ID — `PA000001`, `PA000002`, and so on — to replace their real identity. The only record that connects `PA000001` back to the patient's real hospital MRN is a file called the ledger. This is a simple spreadsheet stored in the workspace folder on the clinical workstation.

**Why this matters:**
The ledger is the only way to:
- Respond if a patient withdraws consent and their data must be removed from the dataset
- Trace a problem in the AI model back to the specific patient whose data may have caused it
- Produce records for an ethics board audit

If the workspace folder is deleted — accidentally, during a system migration, or by an IT cleanup — the ledger is gone. There is no backup. There is no way to recover it. There is no way to verify it has not been quietly corrupted.

**What we are proposing:**
A checksum that verifies the ledger is intact every time the app opens. An automatic backup copy to a second location after every pipeline run. A startup warning if the ledger cannot be verified. This takes one day to implement.

---

## Section 2 — The Operational Issues

These are issues that are not dangerous today but will create real friction as the project grows.

---

### 2.1 Onboarding New Institutions

Every hospital runs a different imaging system. Philips, Siemens, GE, and IntelePACS all organize DICOM metadata differently. The current anonymization list was built from MUHC and MSKCC data. When we onboard Institution #3, their scanner may store patient information in locations we have never seen before, which the pipeline will miss silently.

There is currently no standard process for checking this before a new site goes live. We are proposing a formal onboarding checklist: before any real patient data is processed at a new site, run the audit tool on a small test batch and review the findings with the local coordinator. This becomes the standard step before any institution is considered active.

---

### 2.2 The App Does Not Behave Like a Proper Mac App

When a user double-clicks the SarcomaAI icon:
- The icon bounces in the dock while the app loads
- The bouncing stops — but the icon goes dead
- There is no dot underneath the icon indicating the app is running
- Clicking the icon does nothing
- Cmd+Q does nothing
- The only way to close the app is to open Activity Monitor, find the SarcomaAI process, and force-quit it

This is a known technical issue with how the app is packaged. It makes the application feel broken and unprofessional, which is a problem when the users are clinical staff at hospital sites who are evaluating whether to trust and use this tool.

The fix is well-understood and has been scoped. We need to validate one component (the DICOM viewer inside the fixed window environment) before committing, which is a few hours of testing. Once validated, the fix is small — approximately two days of implementation.

---

### 2.3 The App is Too Large to Install Easily at Hospitals

The application installer (the `.dmg` file for macOS) is currently over 500MB. This causes two problems:

First, many hospital IT departments have policies that restrict the installation of large executables. Some trigger automatic antivirus scanning for anything above a certain size, which can quarantine the app on first launch. Getting approval for installation at a new site currently requires navigating these processes manually.

Second, every time we update the app, the site must download and reinstall the full 500MB package. This creates friction for updates and means sites may delay updating, leaving them on older versions with unresolved issues.

One library (`pyCERR`) that we bundle contributes approximately 200MB but is only used for one specific function that can be replaced with a lighter alternative. Removing it roughly halves the installer size. This is the immediate fix. A longer-term alternative is distributing the application as a standard software package that installs via a single command in the terminal — a distribution method that is more familiar to IT departments and makes updates trivial.

---

## Section 3 — The Proposed Additions (Claude Integration)

Beyond fixing existing issues, we are proposing to add a Claude-powered assistant layer to the application. This is not cosmetic — it addresses specific operational gaps.

---

### 3.1 Automated Anonymization QC (Highest Value)

Once the post-pipeline audit infrastructure exists (described in Section 1.1), we can surface it through a conversational interface. Instead of a coordinator having to read a technical log file, they can ask:

> "Check the anonymization on the last 10 patients we processed."

Claude reads the audit results and responds in plain language, flagging anything that needs attention. This is the most important use of the Claude integration because it makes a safety-critical step accessible to non-technical users who are doing the work at clinical sites.

---

### 3.2 Workspace Assistant (Operational Efficiency)

The second integration gives a coordinator or PI a way to query the state of their institution's data without navigating the app manually. Examples of what this enables:

> "How many patients are we missing T2 selections for?"
> "What happened in the last pipeline run?"
> "Give me a summary of our data readiness I can send to the study coordinator at McGill."

This is particularly useful for the lead researcher who is overseeing data collection across multiple sites and needs a quick status picture without logging into each site's workstation.

---

### 3.3 Cross-Site Coordination (Future)

When the federated learning phase begins, a central coordinator needs to know which sites are ready for a training round. The architecture we are designing now can support a future where Claude can be asked:

> "Which sites are ready for federated round 3?"

And receive a summary drawn from each institution's local data — without any patient data leaving those institutions. This is built on top of the same infrastructure as the two priorities above, so designing it correctly now avoids a rewrite later.

---

## Section 4 — Proposed Plan and Order of Work

The following order is based on risk level, not complexity. The most dangerous issues are addressed before the operational improvements, and the operational improvements before the new capabilities.

| Step | What | Why Now |
|---|---|---|
| 1 | Anonymization audit + verification | Highest risk, should have been there from day one |
| 2 | Ledger backup + integrity check | One day of work, eliminates a governance risk |
| 3 | Dock bug fix (after viewer validation) | Every user sees this every session |
| 4 | Private tag audit + scout image detection | Completes the anonymization QC layer |
| 5 | Per-institution anonymization fields | Required before onboarding Institution #3 |
| 6 | DICOM QC assistant (Claude — Priority 1) | Surfaces audit results to non-technical users |
| 7 | Workspace assistant (Claude — Priority 2) | Operational efficiency for coordinators |
| 8 | Installer size reduction | Reduces IT friction at new sites |
| 9 | Distribution restructure | Long-term maintenance and update efficiency |
| 10 | Cross-site coordination assistant | When federated learning phase begins |

---

## Section 5 — What Happens If We Do Not Act

**On the anonymization gap:** The risk is not theoretical. Every new institution has a different PACS system. The probability that Institution #3 has a private tag structure our pipeline does not catch is high. We will not know it happened until someone audits the data. At that point we have a reportable breach, not a close call.

**On the ledger:** Someone will eventually delete or migrate a workspace folder without realizing the ledger is in it. When that happens, we lose the ability to respond to patient withdrawal requests and the ability to produce ethics audit records for those patients. There is no recovery path.

**On the dock bug and app size:** These do not break the science. But they do affect whether a clinical team at a new institution trusts the tool enough to use it consistently. A tool that feels broken is a tool that gets used inconsistently. Inconsistent use means incomplete datasets. Incomplete datasets mean weaker models.

**On the Claude integration:** This is additive. Not acting here has no immediate consequence — the app continues to function as it does today. The value is in making the safety-critical anonymization step accessible to the non-technical coordinators who run the workflow day to day.

---

## Summary

The application is functional and the core science is sound. The two issues that require immediate attention before onboarding any additional institutions are the anonymization verification gap and the ledger durability gap — both are privacy and governance risks with no recovery path if triggered. The operational improvements (dock bug, app size, onboarding process) are important for scaling but do not carry the same urgency. The Claude integration is the right next capability investment and is designed to make the safety-critical parts of the workflow accessible to the clinical staff who do the work.
