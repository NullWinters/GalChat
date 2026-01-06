from langchain_deepseek import ChatDeepSeek
from dotenv import load_dotenv

load_dotenv()

deepseek = ChatDeepSeek(
    model="deepseek-chat",
    temperature=0.5,
    max_tokens=512,
    timeout=10,
    max_retries=2
)
