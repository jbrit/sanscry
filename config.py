import os
from dotenv import load_dotenv

load_dotenv()

RPC_URL = os.environ["RPC_URL"]
DATABASE_URL = os.environ["DATABASE_URL"]
