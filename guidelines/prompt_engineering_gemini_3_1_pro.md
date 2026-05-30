# Prompt Engineering Guidelines: Gemini 3.1 Pro (High)
*Tailored for the Resume Tailoring Evaluator-Optimizer Loop*

This document outlines the specific prompt engineering best practices for utilizing **Gemini 3.1 Pro (High)** in our iterative resume generation and evaluation (Generator-Critic) workflow. 

Gemini 3.1 Pro is optimized for deep reasoning, agentic tool use, and long-context analysis. The "High" thinking mode gives the model more compute to reason through complex tasks natively, meaning we need to structure our prompts to guide its focus without micromanaging its internal logic.

## 1. Core Principles for Gemini 3.1 Pro (High)

*   **Trust the Reasoning Engine:** Because the "High" setting allows for extended internal chain-of-thought, avoid overly prescriptive "step 1, step 2, step 3" instructions for the actual *creative* tasks (like the Generator writing the resume). Let the model figure out *how* to synthesize the text.
*   **Structured Prompting (XML Tags):** Gemini 3.1 Pro excels when context and instructions are compartmentalized. Always use XML-style tags or markdown headers to delineate sections:
    *   `<base_resume>`: The immutable source of truth.
    *   `<current_draft>`: The resume in its current iteration.
    *   `<critic_feedback>`: Feedback from the Evaluator.
    *   `<task_instructions>`: The core objective.
*   **Context Ordering:** Always place large contextual payloads (e.g., the `base_html` and `job_description`) at the **beginning** of the prompt. Place the specific, actionable instructions and output constraints at the **end**.
*   **Persona + Task + Context + Format + Examples:** Use this golden formula for all system prompts.

---

## 2. The Evaluator Agent (Critic) Prompts

The Evaluator requires strict logical adherence, hallucination detection, and adherence to a rubric. 

### A. Persona Definition
Define exactly who the Evaluator is based on the `company_type`.
*   **IT Services:** "Act as a rigorous Senior Technical Recruiter at a global IT Services firm (like TCS or Infosys). You prioritize process adherence, specific technology stacks, and verifiable project delivery metrics."
*   **Product/Startup:** "Act as a strict hiring manager at a fast-paced Silicon Valley startup. You despise fluff and passive language (e.g., 'Assisted', 'Maintained'). You demand to see ownership, product impact, and quantifiable business outcomes."

### B. Chain-of-Thought (CoT) for Hallucination Checking
To reliably catch hallucinations, instruct the Evaluator to "think step by step" before returning the structured output.
*   *Prompt Snippet:* "Before assigning the final `hallucinations_found` boolean, carefully compare every single metric (numbers, percentages, timeline durations) in the `<current_draft>` against the `<base_resume>`. If a metric exists in the draft but not in the base, flag it."

### C. Few-Shot Examples (Crucial for the Evaluator)
Provide 1-2 examples of how to format the feedback list.
*   *Example Snippet:*
    ```json
    "feedback": [
      "CRITICAL: The metric 'Increased performance by 20%' in the first bullet is a hallucination. It does not exist in the base resume. Revert this.",
      "STYLE: The second bullet uses passive language ('Was responsible for'). Change this to an active, ownership-driven verb."
    ]
    ```

---

## 3. The Generator Agent Prompts

The Generator needs to synthesize the base resume, the job description, and the critic's feedback into a cohesive narrative without breaking factual boundaries.

### A. Stateless Context Injection
Because we are running a loop, do not use stateful chat history. Pass the required state explicitly in every prompt.
*   *Structure:*
    1. `<base_resume>` (Source of truth)
    2. `<job_description>` (Target alignment)
    3. `<critic_feedback>` (The exact `feedback_str` from the Evaluator)
    4. `<task>`: "Incorporate the critic's feedback into a new draft."

### B. Positive Framing & Fallback Logic
Focus on what the Generator *should* do, rather than a long list of what it shouldn't. Provide an explicit "escape hatch" if the Critic asks for something impossible.
*   *Prompt Snippet:* "If the `<critic_feedback>` asks you to quantify a bullet point, but the `<base_resume>` contains no metrics for that specific task, DO NOT invent numbers. Instead, rewrite the bullet to emphasize the scope of the problem solved or the technical complexity involved, and ignore the request to quantify."

### C. Output Formatting
Gemini 3.1 Pro is highly compliant with output formatting if specified at the end of the prompt.
*   *Prompt Snippet:* "Output the revised resume in valid HTML format only. Do not include markdown wrappers like ```html. Start immediately with the <div> tag."

---

## 4. Prompt Engineering Loop Configuration

*   **Temperature:** Leave at default (`1.0`) for Gemini 3.1 Pro. The "High" reasoning mode relies on default temperature entropy to explore optimal reasoning paths. Lowering it for the Evaluator might cause repetitive looping.
*   **System Instructions vs. User Prompts:** Put the Persona, the strict "No Hallucinations" rule, and output JSON/Pydantic schemas in the **System Prompt**. Put the actual `base_html`, `current_html`, and `feedback` in the **User Prompt**.
