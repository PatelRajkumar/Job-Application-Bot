import os
import asyncpg
import json
import logging
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)

SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")

pool = None

async def init_db():
    global pool
    if not SUPABASE_DB_URL:
        logger.warning("SUPABASE_DB_URL not set. Analytics logging is disabled.")
        return

    try:
        pool = await asyncpg.create_pool(SUPABASE_DB_URL)
        async with pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id UUID PRIMARY KEY,
                    chat_id TEXT,
                    start_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    end_time TIMESTAMP WITH TIME ZONE,
                    company_name TEXT
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS llm_requests (
                    id SERIAL PRIMARY KEY,
                    session_id UUID REFERENCES sessions(session_id),
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    feature TEXT,
                    model TEXT,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    cost_usd NUMERIC,
                    error TEXT
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS evaluations (
                    id SERIAL PRIMARY KEY,
                    session_id UUID REFERENCES sessions(session_id),
                    iteration_number INTEGER,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    passed BOOLEAN,
                    is_hallucinated TEXT,
                    ats INTEGER,
                    manual INTEGER
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS agent_traces (
                    id SERIAL PRIMARY KEY,
                    session_id UUID REFERENCES sessions(session_id),
                    iteration_number INTEGER,
                    agent_role TEXT,
                    prompt_text TEXT,
                    raw_response TEXT,
                    parsed_output TEXT,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS email_searches (
                    id SERIAL PRIMARY KEY,
                    session_id UUID REFERENCES sessions(session_id),
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    domain TEXT,
                    layers_tried JSONB,
                    successful_layer TEXT,
                    emails_found TEXT,
                    credits_used JSONB
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS funnel_events (
                    id SERIAL PRIMARY KEY,
                    session_id UUID REFERENCES sessions(session_id),
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    event_type TEXT
                )
            ''')
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")

async def log_session_start(session_id: uuid.UUID, chat_id: str, company_name: str = None):
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO sessions (session_id, chat_id, company_name) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
                session_id, str(chat_id), company_name
            )
    except Exception as e:
        logger.error(f"Error logging session start: {e}")

async def update_session(session_id: uuid.UUID, company_name: str = None, end_time: bool = False):
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            if company_name and end_time:
                await conn.execute(
                    "UPDATE sessions SET company_name = $1, end_time = CURRENT_TIMESTAMP WHERE session_id = $2",
                    company_name, session_id
                )
            elif company_name:
                await conn.execute(
                    "UPDATE sessions SET company_name = $1 WHERE session_id = $2",
                    company_name, session_id
                )
            elif end_time:
                await conn.execute(
                    "UPDATE sessions SET end_time = CURRENT_TIMESTAMP WHERE session_id = $1",
                    session_id
                )
    except Exception as e:
        logger.error(f"Error updating session: {e}")

async def log_llm_request(session_id: uuid.UUID, feature: str, model: str, prompt_tokens: int, completion_tokens: int, cost_usd: float, error: str = None):
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO llm_requests (session_id, feature, model, prompt_tokens, completion_tokens, cost_usd, error) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                session_id, feature, model, prompt_tokens, completion_tokens, cost_usd, error
            )
    except Exception as e:
        logger.error(f"Error logging llm request: {e}")

async def log_evaluation(session_id: uuid.UUID, iteration_number: int, passed: bool, is_hallucinated: str, ats: int, manual: int):
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO evaluations (session_id, iteration_number, passed, is_hallucinated, ats, manual) VALUES ($1, $2, $3, $4, $5, $6)",
                session_id, iteration_number, passed, is_hallucinated, ats, manual
            )
    except Exception as e:
        logger.error(f"Error logging evaluation: {e}")

async def log_agent_trace(session_id: uuid.UUID, iteration_number: int, agent_role: str, prompt_text: str, raw_response: str, parsed_output: str):
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO agent_traces (session_id, iteration_number, agent_role, prompt_text, raw_response, parsed_output) VALUES ($1, $2, $3, $4, $5, $6)",
                session_id, iteration_number, agent_role, prompt_text, raw_response, parsed_output
            )
    except Exception as e:
        logger.error(f"Error logging agent trace: {e}")

async def log_email_search(session_id: uuid.UUID, domain: str, layers_tried: dict, successful_layer: str, emails_found: list, credits_used: dict):
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO email_searches (session_id, domain, layers_tried, successful_layer, emails_found, credits_used) VALUES ($1, $2, $3, $4, $5, $6)",
                session_id, domain, json.dumps(layers_tried), successful_layer, json.dumps(emails_found), json.dumps(credits_used)
            )
    except Exception as e:
        logger.error(f"Error logging email search: {e}")

async def log_funnel_event(session_id: uuid.UUID, event_type: str):
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO funnel_events (session_id, event_type) VALUES ($1, $2)",
                session_id, event_type
            )
    except Exception as e:
        logger.error(f"Error logging funnel event: {e}")

async def close_db():
    global pool
    if pool:
        await pool.close()
