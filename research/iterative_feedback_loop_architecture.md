# Research: Iterative AI Feedback Loops for Resume Optimization

## Overview
This document explores the architectural patterns and prompt writing strategies necessary for implementing an iterative AI feedback loop in resume optimization. The goal is to create a system that iteratively improves a resume to maximize its impact while strictly maintaining grounding in the original resume's truthful facts.

## 1. Architectural Patterns for Feedback Loops

To move beyond single-pass LLM generation, an **Iterative Refinement** architecture is necessary. The most suitable pattern for this use case is the **Evaluator-Optimizer (or Critic-Generator) Pattern**.

### Core Components
1. **Generator Agent (The Writer):** Responsible for drafting the resume modifications based on the initial input or feedback from previous iterations.
2. **Evaluator Agent (The Critic/Judge):** Analyzes the Generator's draft against a specific rubric (such as the new contextual depth and quantification metrics) and provides structured feedback.
3. **State/Context Manager:** Maintains the original source of truth (the original resume) and tracks the iteration history to prevent drift.
4. **Stopping Criteria:** A mechanism to halt the loop, such as a maximum number of iterations (e.g., 3-5), a passing score from the Evaluator, or a convergence state where no further improvements are suggested.

### Variations to Consider
* **Self-Refine:** A single model instance performs both generation and critique sequentially. It's simpler to implement but might suffer from "blind spots" if the model's biases affect both generation and evaluation.
* **Multi-Agent / Dual-Model:** Using a separate model or a separately prompted agent for the Evaluator. For example, using a highly strict persona prompt for the Evaluator and an optimization-focused persona for the Generator.

### Token and Context Management
A major risk of the Evaluator-Optimizer pattern is runaway token costs. If the system maintains a running chat history of every draft and critique, the context window will bloat exponentially. 
*   **Stateless Execution:** The Orchestrator must manage state, not the LLM. Provide only the most recent draft and the current iteration's feedback to the Generator. Discard intermediate drafts.
*   **Concise Structured Feedback:** The Evaluator must output strict JSON (via Pydantic) to avoid verbose conversational tokens.
*   **Hard Iteration Limits:** Always enforce a `max_iterations` cap (e.g., 3 loops) to ensure the system converges and exits predictably.

## 2. Maintaining Grounding & Truthfulness (Preventing Hallucination)

The primary risk of iterative refinement is that the LLM may "drift" from the original facts, hallucinating metrics or skills to satisfy the Evaluator's demands for stronger impact. To prevent this, the system must enforce strict grounding.

### Strategies for Resume Grounding
1. **Source-of-Truth Anchoring (RAG approach):** 
   In every generation and evaluation step, the *original unoptimized resume* must be provided as the immutable source of truth. The LLM must be forced to map any new claim back to the source text.
2. **Faithfulness / Hallucination Judge:**
   The Evaluator agent must explicitly check for fabricated information. The feedback loop should have a specific step: "Does this draft contain any skills, metrics, or experiences not explicitly present in or directly derivable from the original resume?"
3. **Fact-Extraction Pre-processing:**
   Before generation begins, extract a structured list of atomic facts, metrics, and skills from the original resume. The Generator is instructed that it can *only* use elements from this approved list.
4. **Explicit Constraints / "Admit Defeat" Fallback:**
   If the Evaluator demands a quantifiable metric but the original resume lacks one, the Generator must be prompted to *preserve the lack of quantification* rather than inventing a number. The prompt must explicitly authorize the model to "fail" a rubric item if the truth does not support it.

## 3. Prompt Writing Strategies

To make this architecture work, prompts must be highly specific, separating the concerns of optimization and truthfulness.

### The Generator Prompt
The Generator's prompt should focus on structural improvement, impact maximization, and adherence to constraints.

* **Key Directives:**
  * *"You are an expert resume writer. Your task is to optimize the provided draft based on the Critic's feedback."*
  * *"CRITICAL CONSTRAINT: You must only use facts, metrics, and skills present in the <ORIGINAL_RESUME>. Do not invent or infer numbers, project sizes, or technologies."*
  * *"If the Critic asks for a metric but none exists in the original text, you must focus on improving the context and action verbs instead. Do not fabricate data."*

### The Evaluator / Critic Prompt
The Evaluator's prompt must embody the strict recruiter persona and check for both quality and grounding.

* **Key Directives:**
  * *"You are a strict, skeptical Silicon Valley recruiter. Review the <CURRENT_DRAFT> against the provided rubric."*
  * *"Step 1 (Faithfulness Check): Compare the draft to the <ORIGINAL_RESUME>. Identify any metrics, skills, or claims in the draft that do not exist in the original. If you find any, instruct the writer to remove them immediately."*
  * *"Step 2 (Quality Check): Identify bullet points that lack quantifiable impact or contextual depth. Provide specific, actionable feedback on how to improve the phrasing using ONLY the facts available in the original resume."*
  * *"Output your feedback as a structured list of actionable items."*

### Dynamic Personas based on Company Type
To account for inherent biases in the hiring market (especially the bias product companies have against IT services backgrounds), the Generator and Evaluator prompts must dynamically adapt based on the target `company_type` (e.g., `it_services` vs `product_startup`).

* **Targeting Product Companies / Startups:** 
  * The Evaluator should be prompted to aggressively penalize "service-heavy" jargon (e.g., "maintained", "supported") and demand evidence of ownership, scalability, and measurable impact.
  * The Generator should be instructed to reframe IT service experience to highlight architectural complexity and problem-solving, overcoming the bias against "task-execution" profiles.
* **Targeting IT Services:**
  * The Evaluator should prioritize keyword matching, framework familiarity, and clearly defined project roles.

## Next Steps
1. Finalize the exact scoring rubric (Evaluation Framework) that the Evaluator will use.
2. Develop the Python orchestration logic (the loop) connecting the Generator and Evaluator.
3. Run test iterations to calibrate the stopping criteria and prompt constraints.
