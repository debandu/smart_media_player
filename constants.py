from dotenv import load_dotenv
import os
load_dotenv(".env")

GROQ_API_KEY=os.environ.get("GROQ_API_KEY")
MODEL=os.environ.get("MODEL")
BASE_URL=os.environ.get("BASE_URL")
CHROMA_DB_PATH=os.environ.get("CHROMA_DB_PATH")