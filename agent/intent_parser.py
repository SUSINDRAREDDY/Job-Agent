from typing import Optional, List
from pydantic import BaseModel, Field
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable

from config import get_default_llm

# Define the structured output we want
class JobSearchIntent(BaseModel):
    """Structured extraction of job search criteria from natural language."""
    role_keywords: List[str] = Field(description="Keywords related to the job role/title (e.g. 'AI Engineer', 'Python')")
    location: Optional[str] = Field(None, description="Global location preference (e.g. 'San Francisco', 'Remote')")
    salary_min: Optional[float] = Field(None, description="Minimum salary amount if specified")
    salary_max: Optional[float] = Field(None, description="Maximum salary amount if specified")
    salary_currency: Optional[str] = Field(None, description="Currency symbol or code (e.g. '$', 'USD')")
    salary_period: Optional[str] = Field(None, description="Pay period (e.g. 'hour', 'year', 'month')")
    job_type: Optional[str] = Field(None, description="Type of job (e.g. 'Full-time', 'Internship', 'Contract')")
    remote: Optional[bool] = Field(None, description="True if remote is explicitly requested")

def get_intent_parser_chain() -> Runnable:
    """
    Creates a Runnable chain that takes a 'query' string and returns a JobSearchIntent.
    
    Note: Uses deepseek-chat (not reasoner) because with_structured_output 
    requires tool_choice which reasoner doesn't support.
    """
    from langchain_openai import ChatOpenAI
    from config import MAIN_MODEL, OPENROUTER_BASE_URL, get_openrouter_api_key
    
    # Use ChatOpenAI with GLM-4.7 via OpenRouter for robust structured output
    llm = ChatOpenAI(
        model=MAIN_MODEL,
        temperature=0,
        api_key=get_openrouter_api_key(),
        base_url=OPENROUTER_BASE_URL,
        default_headers={
            "HTTP-Referer": "https://github.com/job-agent",
            "X-Title": "Job Agent"
        }
    )
    
    # Define the prompt
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You are an expert at extracting structured job search criteria from natural language queries. Extract the following fields strictly."),
        ("user", "{query}")
    ])
    
    # Create the structured extraction chain
    chain = prompt | llm.with_structured_output(JobSearchIntent)
    return chain

def parse_user_query(query: str) -> JobSearchIntent:
    """
    Parses a natural language query into a structured JobSearchIntent.
    
    Args:
        query: The user's search string (e.g. 'AI internship 40/hr').
        
    Returns:
        JobSearchIntent object.
    """
    chain = get_intent_parser_chain()
    return chain.invoke({"query": query})
