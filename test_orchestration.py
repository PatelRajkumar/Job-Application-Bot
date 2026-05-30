import os
import sys
import asyncio
import logging
from pathlib import Path

# Add the 'bot' directory to the path so we can import modules
sys.path.append(os.path.join(os.path.dirname(__file__), 'bot'))

from dotenv import load_dotenv
from gemini_client import GeminiClient
from models import ResumeEvaluation

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def run_tests():
    logger.info("Starting Orchestration Tests...")
    
    # Initialize client
    try:
        client = GeminiClient()
    except Exception as e:
        logger.error(f"Failed to initialize GeminiClient: {e}")
        return

    # Load resources
    root_dir = Path(__file__).parent
    master_profile_path = root_dir / 'master_profile.json'
    template_path = root_dir / 'resume_template.html'
    
    if not master_profile_path.exists() or not template_path.exists():
        logger.error("Missing master_profile.json or resume_template.html")
        return
        
    master_profile_json = master_profile_path.read_text(encoding='utf-8')
    template_html = template_path.read_text(encoding='utf-8')

    # Mock Data
    company_type = "product_startup"
    jd = """
    Senior Backend Engineer - StartupX
    We are looking for a highly motivated Backend Engineer to join our fast-paced startup. 
    You will own the backend architecture, build scalable APIs, and take product features from 0 to 1.
    Required Skills:
    - 5+ years experience in Python and Go
    - Strong understanding of microservices architecture
    - Experience taking ownership of complex systems
    - Startup mentality - bias for action, high impact
    """
    
    logger.info("=== TEST 1: Generator Agent (refine_resume) ===")
    current_html = None
    feedback = None
    priority = 'normal'
    research_md = "COMPANY_TYPE: product_startup\nFast-paced startup requiring strong engineering ownership."
    
    try:
        gen_resp = await client.refine_resume(
            jd=jd,
            company_type=company_type,
            master_profile_json=master_profile_json,
            template_html=template_html,
            research_md=research_md,
            current_html=current_html,
            feedback=feedback,
            priority=priority
        )
        raw_response = gen_resp['text']
        
        if not client.is_final_output(raw_response):
            logger.error(f"Generator did not return final output markers. Output:\n{raw_response}")
            return
            
        parsed = client.parse_final_response(raw_response)
        current_html = parsed['tailored_html']
        logger.info("Successfully generated tailored HTML.")
        
    except Exception as e:
        logger.error(f"Test 1 failed: {e}")
        return

    logger.info("\n=== TEST 2: Evaluator Agent (evaluate_resume) ===")
    try:
        eval_result, eval_usage = await client.evaluate_resume(
            current_html=current_html,
            master_profile_json=master_profile_json,
            jd=jd,
            company_type=company_type,
            research_md=research_md,
            priority=priority
        )
        
        logger.info(f"Evaluator returned Valid Pydantic Schema: {isinstance(eval_result, ResumeEvaluation)}")
        logger.info(f"Passed: {eval_result.passed}")
        logger.info(f"Hallucinations Found: {eval_result.is_hallucinated}")
        logger.info(f"Feedback: {eval_result.feedback}")
        logger.info(f"ATS Score: {eval_result.ats_score}")
        logger.info(f"Manual Score: {eval_result.manual_score}")
        
    except Exception as e:
        logger.error(f"Test 2 failed: {e}")
        return

    logger.info("\n=== TEST 3: Hallucination Detection ===")
    hallucinated_html = current_html.replace(
        "</body>",
        "<ul><li>Increased company revenue by $500 Million in 1 day using advanced quantum algorithms.</li></ul></body>"
    )
    
    try:
        hallucinated_eval, hallucinated_usage = await client.evaluate_resume(
            current_html=hallucinated_html,
            master_profile_json=master_profile_json,
            jd=jd,
            company_type=company_type,
            research_md=research_md,
            priority=priority
        )
        
        logger.info(f"Hallucinations Found (Expected: True): {hallucinated_eval.is_hallucinated}")
        logger.info(f"Passed (Expected: False): {hallucinated_eval.passed}")
        logger.info(f"Feedback on hallucination: {hallucinated_eval.feedback}")
        
        if hallucinated_eval.is_hallucinated:
            logger.info("✅ Hallucination detection passed!")
        else:
            logger.error("❌ Evaluator failed to detect the injected hallucination.")
            
    except Exception as e:
        logger.error(f"Test 3 failed: {e}")
        return

    logger.info("\n✅ All orchestration tests completed.")

if __name__ == "__main__":
    asyncio.run(run_tests())
