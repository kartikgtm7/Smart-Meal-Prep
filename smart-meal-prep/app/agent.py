import datetime
import re
import json
import logging
import os
import sys
from typing import AsyncGenerator
from pydantic import BaseModel, Field, model_validator
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from google.adk.workflow import Workflow
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.models import Gemini
from google.genai import types

from .config import config

logger = logging.getLogger("meal_prep_security")
logging.basicConfig(level=logging.INFO)

# Define schemas for input/state
class WorkflowInput(BaseModel):
    message: str

    @model_validator(mode="before")
    @classmethod
    def parse_content(cls, value: Any) -> Any:
        from google.genai import types
        if isinstance(value, str):
            return {"message": value}
        
        # Robustly check if the object is content-like (e.g. from google-genai, vertexai, etc.)
        is_content = False
        class_name = value.__class__.__name__ if hasattr(value, "__class__") else ""
        if isinstance(value, types.Content) or hasattr(value, "parts") or "Content" in class_name:
            is_content = True
            
        if is_content:
            text = ""
            parts = getattr(value, "parts", []) or []
            for part in parts:
                if isinstance(part, str):
                    text += part
                elif hasattr(part, "text") and part.text:
                    text += part.text
                elif isinstance(part, dict) and "text" in part:
                    text += part["text"] or ""
                elif hasattr(part, "to_dict"):
                    try:
                        p_dict = part.to_dict()
                        if isinstance(p_dict, dict) and "text" in p_dict:
                            text += p_dict["text"] or ""
                    except Exception:
                        pass
            return {"message": text}
            
        elif isinstance(value, dict):
            if "parts" in value:
                parts = value.get("parts") or []
                text = ""
                for part in parts:
                    if isinstance(part, dict) and "text" in part:
                        text += part["text"] or ""
                    elif isinstance(part, str):
                        text += part
                    elif hasattr(part, "text") and part.text:
                        text += part.text
                return {"message": text}
            if "message" in value:
                return value
        return value

class MealPrepState(BaseModel):
    user_query: str = ""
    sanitized_query: str = ""
    proposed_plan: str = ""
    feedback: str = ""
    feedback_count: int = 0
    approved: bool = False
    security_violation: bool = False
    security_reason: str = ""

# Define model options
gemini_model = Gemini(
    model=config.model,
    retry_options=types.HttpRetryOptions(attempts=3)
)

# Define MCP server executable parameters dynamically
mcp_server_path = os.path.join(os.path.dirname(__file__), "mcp_server.py")
mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=[mcp_server_path],
        )
    )
)

# 1. Specialized Meal Planner Sub-Agent (Wired with MCP to check pantry and recipes)
meal_planner_agent = LlmAgent(
    name="meal_planner",
    model=gemini_model,
    tools=[mcp_toolset],
    instruction=(
        "You are a professional chef. Create custom, weekly dinner menus and recipes based on user preferences. "
        "Use the get_pantry_items tool to check what ingredients are in the user's pantry so you can plan meals using "
        "available items and reduce waste. You can also use search_recipes to find existing recipe matches. "
        "Ensure nutritional balance, variety, and focus purely on culinary instruction and meal prep schedules."
    ),
)

# 2. Specialized Grocery List Sub-Agent (Wired with MCP to save ingredients to list)
grocery_list_agent = LlmAgent(
    name="grocery_list_generator",
    model=gemini_model,
    tools=[mcp_toolset],
    instruction=(
        "You are an efficient kitchen organizer. Extract a comprehensive grocery shopping list from a meal plan. "
        "For each item on the grocery list, use the add_to_grocery_list tool to record the needed ingredient and quantity. "
        "Categorize list items by supermarket aisle (e.g., Produce, Meat, Dairy, Pantry) and estimate quantities."
    ),
)

# 3. Main Orchestrator Agent (with sub-agents wired as tools)
orchestrator_agent = LlmAgent(
    name="orchestrator",
    model=gemini_model,
    tools=[AgentTool(meal_planner_agent), AgentTool(grocery_list_agent)],
    instruction=(
        "You are the Kitchen Orchestrator. Help the user plan their weekly meals and shopping list.\n\n"
        "Instructions:\n"
        "1. Call the `meal_planner` tool to generate a detailed recipe plan.\n"
        "2. Call the `grocery_list_generator` tool with the generated plan to assemble a categorized shopping list.\n"
        "3. Incorporate any adjustments or feedback provided by the user in the prompt history.\n"
        "Provide a structured, beautifully formatted final response with both the meal plan and grocery list."
    ),
)

# 4. Security Checkpoint function node
def security_checkpoint(ctx: Context, node_input: WorkflowInput) -> Event:
    user_message = node_input.message
    
    # 4a. PII Scrubbing
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    phone_pattern = r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'
    sanitized_message = re.sub(email_pattern, "[REDACTED_EMAIL]", user_message)
    sanitized_message = re.sub(phone_pattern, "[REDACTED_PHONE]", sanitized_message)
    
    # 4b. Prompt Injection Detection
    injection_keywords = ["ignore instructions", "system prompt", "override instructions", "you are now", "developer mode"]
    is_injection = any(kw in sanitized_message.lower() for kw in injection_keywords)
    
    # 4c. Domain-Specific Rule: Reject non-food / non-cooking topics
    non_cooking_keywords = ["malware", "virus", "exploit", "hack", "weapons", "drugs", "illegal"]
    is_dangerous = any(kw in sanitized_message.lower() for kw in non_cooking_keywords)
    
    # 4d. Structured JSON Audit Logging
    audit_log = {
        "timestamp": datetime.datetime.now().isoformat(),
        "session_id": ctx.session.id,
        "pii_redacted": sanitized_message != user_message,
        "injection_detected": is_injection,
        "unsafe_content": is_dangerous,
    }
    
    if is_injection or is_dangerous:
        audit_log["severity"] = "CRITICAL"
        audit_log["status"] = "REJECTED"
        logger.warning(json.dumps(audit_log))
        
        ctx.state["security_violation"] = True
        ctx.state["security_reason"] = "Safety check violation."
        return Event(
            output="Request blocked by security checkpoint.",
            route="SECURITY_EVENT",
            content=types.Content(role="model", parts=[types.Part.from_text("⚠️ Security Checkpoint: Unsafe request detected and blocked.")])
        )
        
    audit_log["severity"] = "INFO"
    audit_log["status"] = "PASSED"
    logger.info(json.dumps(audit_log))
    
    ctx.state["user_query"] = user_message
    ctx.state["sanitized_query"] = sanitized_message
    
    return Event(
        output=sanitized_message,
        route="safe"
    )

# Security Error Terminal Node
def security_error_node(node_input: str) -> Event:
    return Event(output="Access denied. Safety violation.")

# 5. Human-in-the-Loop Approval Check Node
async def approve_meal_plan(ctx: Context, node_input: Any) -> AsyncGenerator[Event, None]:
    # Capture proposed plan from previous LlmAgent node
    proposed_plan = ""
    if node_input:
        if isinstance(node_input, str):
            proposed_plan = node_input
        elif hasattr(node_input, "parts") and node_input.parts:
            proposed_plan = "".join([p.text for p in node_input.parts if p.text])
        elif isinstance(node_input, dict) and "parts" in node_input:
            parts = node_input.get("parts") or []
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    proposed_plan += part["text"] or ""
                elif isinstance(part, str):
                    proposed_plan += part
                elif hasattr(part, "text") and part.text:
                    proposed_plan += part.text
        else:
            proposed_plan = str(node_input)
            
    if proposed_plan:
        ctx.state["proposed_plan"] = proposed_plan
        
    # Check if user has resumed with approval decision
    if ctx.resume_inputs and "approval" in ctx.resume_inputs:
        user_response = ctx.resume_inputs["approval"].strip().lower()
        if user_response == "yes" or "approve" in user_response:
            ctx.state["approved"] = True
            yield Event(
                content=types.Content(role="model", parts=[types.Part.from_text("✅ Recipe plan approved! Finalizing...")]),
                route="approved"
            )
            return
        else:
            ctx.state["feedback_count"] += 1
            ctx.state["feedback"] = user_response
            yield Event(
                output=f"User feedback: {user_response}",
                content=types.Content(role="model", parts=[types.Part.from_text(f"🔄 Re-orchestrating with feedback: '{user_response}'...")]),
                route="feedback"
            )
            return
            
    # Interrupt execution and request user approval
    yield RequestInput(
        interrupt_id="approval",
        message="Here is your proposed meal plan and grocery list. Do you approve? (Reply 'yes' to finalize, or specify any adjustments you want)."
    )

# Finalize Node
def finalize_plan(ctx: Context, node_input: Any) -> Event:
    final_plan = ctx.state.get("proposed_plan", "No plan generated.")
    summary = f"🎉 **Meal Prep Plan Finalized!** 🎉\n\n{final_plan}"
    return Event(
        output=summary,
        content=types.Content(role="model", parts=[types.Part.from_text(summary)])
    )

# Configure the 2.0 Workflow with dictionary-mapped conditional routes
root_agent = Workflow(
    name="smart_meal_prep_workflow",
    edges=[
        ('START', security_checkpoint),
        (security_checkpoint, {
            "safe": orchestrator_agent,
            "SECURITY_EVENT": security_error_node
        }),
        (orchestrator_agent, approve_meal_plan),
        (approve_meal_plan, {
            "feedback": orchestrator_agent,
            "approved": finalize_plan
        })
    ],
    description="A multi-agent meal planner and shopping list assistant with built-in safety controls.",
    input_schema=WorkflowInput,
    state_schema=MealPrepState
)

# Export ADK App
app = App(
    root_agent=root_agent,
    name="app"
)
