"""Environment variable loading for AShareSight A-share data sources."""

import logging
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

# A-share data source configuration
CN_DATA_PRIMARY = os.getenv("CN_DATA_PRIMARY", "rqdatac").strip()
CN_DATA_FALLBACK = os.getenv("CN_DATA_FALLBACK", "eastmoney").strip()

# Web Search
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()

# Eastmoney fallback
EASTMONEY_USER_AGENT = os.getenv("EASTMONEY_USER_AGENT", "AShareSight (contact@example.com)").strip()
EASTMONEY_TIMEOUT = int(os.getenv("EASTMONEY_TIMEOUT", "12"))
