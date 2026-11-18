"""Keep the offline suite independent of developer credentials and local .env."""

import os

os.environ["MEDVED_DISABLE_DOTENV"] = "1"
os.environ["NLP_MODE"] = "mock"
