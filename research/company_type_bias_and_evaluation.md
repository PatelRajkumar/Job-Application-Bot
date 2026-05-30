# Research: Impact of Company Type on Resume Evaluation in India

## 1. Overview and Validation of Assumptions
Recent research into the Indian tech hiring landscape strongly validates the assumption that a candidate's resume must be dynamically tailored based on the target company type—specifically when contrasting **IT Services** (e.g., TCS, Infosys, Wipro) against **Product Engineering Companies and Startups** (e.g., Google, Swiggy, early-stage ventures).

### Validated Assumptions:
1.  **Divergent Evaluation Frameworks:** IT services and product companies evaluate resumes using completely different rubrics. What is considered a strong resume for one may be rejected by the other.
2.  **Bias Against IT Services Backgrounds:** Product companies often exhibit a bias against candidates transitioning from an IT services background (often referred to as WITCH companies). This stems from a perception that service-based work is maintenance-heavy, process-oriented, and lacks deep technical ownership or exposure to scale.
3.  **Need for Dynamic Prompts:** Therefore, the AI Generator and Evaluator *must* use dynamic system prompts and rubrics based on the target company type to successfully bypass these biases.

## 2. IT Services vs. Product/Startup Evaluation Rubrics

| Evaluation Criteria | IT Services Focus | Product Company / Startup Focus |
| :--- | :--- | :--- |
| **Primary Value Add** | Predictability, process adherence, domain knowledge. | Innovation, technical depth, problem-solving, scale. |
| **Keywords & Skills** | Broad tech stacks, specific frameworks, certifications (AWS, Azure), methodologies. | Core fundamentals (DSA, System Design), modern tech, scalable architecture. |
| **Experience Narrative** | Project size, client domain, responsibilities, maintenance/support work. | "0→1" building, measurable impact, ownership, performance optimization. |
| **Resume Format** | Keyword-heavy, detailed, sometimes multi-page to list all projects/clients. | Concise, strict 1-page, outcome-focused (STAR method), ATS-friendly. |
| **Red Flags** | Lack of specific framework knowledge, short tenure. | "Service-heavy" language (e.g., "Maintained," "Assisted," "Assigned tickets"). |

## 3. Strategies for Bypassing the "IT Services Bias"

When applying to a Product Company or Startup with an IT services background (e.g., 4 years experience), the resume must undergo a narrative transformation to signal a "Product Mindset."

### A. Narrative Transformation (The Generator's Job)
*   **Shift from Responsibilities to Impact:** The generator must rewrite passive, service-oriented bullets (e.g., "Worked on Java backend module for banking client") into impact-driven statements (e.g., "Optimized backend API, reducing response time by 40% for 10k+ daily active users").
*   **Highlight "Product-Like" Achievements:** Even within a service role, the generator should emphasize instances of automation, architectural improvements, or complex problem-solving over routine maintenance.
*   **Obfuscate "Service Jargon":** Remove or downplay terms like "support," "maintenance," "client delivery," and instead use terms like "architected," "owned," "scaled," and "implemented."

### B. The Strict Product Evaluator (The Critic's Job)
The Evaluator prompt for a Product/Startup target must act as a highly skeptical engineering manager.
*   **Impact Check:** "Does this bullet point explain *why* the work mattered and *what* the measurable outcome was?"
*   **Ownership Check:** "Does the candidate sound like an owner or a task-executor?"
*   **Bias Check:** "Does this resume read like a typical IT services profile? If so, instruct the Generator to rewrite the verbs and focus on technical complexity rather than project management."

## 4. Implementation Impact for the AI System

To implement this, the orchestrator must dynamically select the Persona, System Prompt, and Rubric based on a new input variable: `company_type`.

*   **Target: `it_services`**
    *   **Evaluator:** Checks for broad keyword coverage, clearly defined project roles, and familiarity with enterprise tools.
    *   **Generator:** Ensures all required tech stack keywords from the JD are heavily featured.
*   **Target: `product_startup`**
    *   **Evaluator:** Aggressively penalizes passive verbs and lack of quantifiable metrics. Checks for "service bias" language.
    *   **Generator:** Focuses on the STAR method, emphasizing scalability, system design, and individual ownership.

---
**Conclusion:** A one-size-fits-all rubric will fail. By integrating `company_type` as a core parameter in the prompt generation logic, the AI can actively mitigate the structural biases present in the Indian tech hiring ecosystem.
