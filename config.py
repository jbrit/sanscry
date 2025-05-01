import os
from dotenv import load_dotenv

load_dotenv()

RPC_URL = os.environ["RPC_URL"]
FAST_RPC_URL = os.environ["FAST_RPC_URL"]
POOLS_DATABASE_URL = os.environ["POOLS_DATABASE_URL"]
DATABASE_URL = os.environ["DATABASE_URL"]
