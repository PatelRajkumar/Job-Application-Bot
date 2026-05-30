import asyncio
import os
from dotenv import load_dotenv

# Load environment variables (including SUPABASE_DB_URL)
load_dotenv()

from bot import analytics_logger

async def main():
    print("Initializing Supabase database tables...")
    await analytics_logger.init_db()
    print("Database tables created successfully!")
    await analytics_logger.close_db()

if __name__ == "__main__":
    asyncio.run(main())
