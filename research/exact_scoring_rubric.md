# Exact Resume Scoring Rubric: ATS & Recruiter Manual Review

## Overview
This document outlines a comprehensive scoring rubric designed for an AI Evaluator in the iterative resume refinement loop. 

A resume must pass two distinct "gatekeepers" to secure an interview:
1. **The ATS (Automated Tracking System):** Scans for parsability, basic criteria, and keyword matching.
2. **The Recruiter (Manual Review):** Conducts a 6-10 second scan focusing on impact, context, career progression, and role fit.

To be effective, the AI feedback loop must optimize and score against **both** sets of criteria.

---

## The Dual-Stage Scoring Rubric (Total: 100 Points)

### Stage 1: ATS Compatibility Parameters (30 Points)
*The goal here is simply not to be automatically rejected. The ATS is looking for rigid data points.*

*   **Keyword Alignment (15 pts):** 
    *   Does the resume contain the exact "must-have" technical skills, tools, and industry terminology found in the job description? 
    *   *Penalty:* -5 points for missing core required skills.
*   **Formatting & Parsability (10 pts):** 
    *   Is the layout simple (single-column preferred)? 
    *   Are standard headings used (e.g., "Work Experience", "Education")? 
    *   Are complex tables, graphics, and unconventional fonts avoided?
*   **Basic Criteria Match (5 pts):** 
    *   Does the resume explicitly state non-negotiable requirements (e.g., specific degree, total years of experience, certifications)?

---

### Stage 2: Recruiter Manual Judgment (70 Points)
*Once parsed by the ATS, a human recruiter will perform a rapid (6-8 second) visual scan. This section optimizes for human psychology, cognitive load, and proof of competence.*

**2.1 The "Top Third" Immediate Impact (20 pts)**
*Recruiters make their initial decision based almost entirely on the top third of the first page.*
*   **Role Relevance (10 pts):** Does the current/most recent job title clearly align with the target role? (e.g., using standard market vocabulary like "Software Engineer" instead of a confusing internal title like "Code Ninja").
*   **Clarity of Intent (10 pts):** Is there a concise, high-impact professional summary that immediately defines the candidate's value proposition without fluff?

**2.2 Experience & Quantifiable Impact (30 pts)**
*Recruiters are looking for proof of ability, not a copy-paste of a job description.*
*   **Outcome-Focused Bullets (15 pts):** Does the first bullet point of the most recent roles focus on outcomes and achievements rather than duties?
*   **Quantification (15 pts):** Are achievements backed by hard numbers (percentages, dollar amounts, time saved, team size, scale of system)? (e.g., Google's XYZ formula: "Accomplished [X] as measured by [Y], by doing [Z]").

**2.3 Career Progression & Professionalism (20 pts)**
*Recruiters assess risk. They look for logical career stories and red flags.*
*   **Upward Mobility (10 pts):** Does the history show a logical growth in responsibility, seniority, or scope of work?
*   **Tenure & Stability (5 pts):** Are employment dates clear? Are short stints or gaps easily explainable or minimized?
*   **Attention to Detail (5 pts):** Is the formatting consistent throughout (fonts, date alignments, bullet styles)? *Any typo or glaring inconsistency immediately fails this check.*

---

## Sources & Research for Optimizing Recruiter Manual Review

To prompt the AI Evaluator effectively to mimic a recruiter, the following industry standards and research findings are used as the foundation:

1.  **Eye-Tracking Studies on Resume Scanning:** Research (such as the famous TheLadders study) consistently shows that recruiters spend roughly 80% of their 6-second scan on six specific data points: Name, Current Title/Company, Previous Title/Company, Employment Start/End Dates, and Education. 
    *   *Optimization Strategy:* Make these elements the most prominent and easily scannable parts of the document.
2.  **The "Top-Third" Rule:** Consensus among hiring managers and career coaches dictates that the top third of the resume acts as the "hook."
    *   *Optimization Strategy:* Place the most relevant skills, a strong summary, and the most recent, highest-impact role immediately at the top.
3.  **Outcome-Based Formatting (The Google XYZ Formula):** Recruiters are trained to look for context and impact. A list of responsibilities signals a "doer," while a list of quantified achievements signals an "achiever."
    *   *Optimization Strategy:* The AI must specifically flag bullet points that start with "Responsible for..." and rewrite them to start with strong action verbs leading to measurable results.
4.  **Standardized Market Vocabulary:** Recruiters scan for familiar patterns. Unique or overly creative formatting and job titles slow down their cognitive processing.
    *   *Optimization Strategy:* Translate niche internal titles into standard industry equivalents (e.g., wrapping the standard title in parentheses).
