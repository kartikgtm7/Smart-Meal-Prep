import pytest
from pydantic import BaseModel, model_validator
from typing import Any

# Try importing the types from google.genai or just simulate it
try:
    from google.genai import types as genai_types
except ImportError:
    genai_types = None

try:
    from vertexai.generative_models import Content as VertexContent, Part as VertexPart
except ImportError:
    VertexContent = None
    VertexPart = None

class WorkflowInput(BaseModel):
    message: str

    @model_validator(mode="before")
    @classmethod
    def parse_content(cls, value: Any) -> Any:
        print(f"parse_content value type: {type(value)}")
        print(f"parse_content value representation: {repr(value)}")
        print(f"is genai_types.Content: {genai_types and isinstance(value, genai_types.Content)}")
        print(f"hasattr(value, 'parts'): {hasattr(value, 'parts')}")
        print(f"class name of value: {value.__class__.__name__}")
        
        if isinstance(value, str):
            return {"message": value}
        
        # Let's check if it is some other Content class (by name)
        is_content_like = False
        if value.__class__.__name__ == "Content":
            is_content_like = True
        elif genai_types and isinstance(value, genai_types.Content):
            is_content_like = True
        elif hasattr(value, "parts"):
            is_content_like = True
            
        if is_content_like:
            text = ""
            parts = getattr(value, "parts", []) or []
            print(f"parts: {parts}")
            for part in parts:
                print(f"part type: {type(part)}")
                if hasattr(part, "text") and part.text:
                    text += part.text
                elif isinstance(part, dict) and "text" in part:
                    text += part["text"] or ""
                elif hasattr(part, "to_dict"):
                    p_dict = part.to_dict()
                    if isinstance(p_dict, dict) and "text" in p_dict:
                        text += p_dict["text"] or ""
                else:
                    try:
                        text += str(part)
                    except:
                        pass
            return {"message": text}
            
        elif isinstance(value, dict):
            if "parts" in value:
                parts = value.get("parts") or []
                text = ""
                for part in parts:
                    if isinstance(part, dict) and "text" in part:
                        text += part["text"] or ""
                    elif hasattr(part, "text") and part.text:
                        text += part.text
                return {"message": text}
            if "message" in value:
                return value
        return value

def test_validation_vertex() -> None:
    if VertexContent is not None:
        c = VertexContent(role="user", parts=[VertexPart.from_text(text="Please plan dinner for this week using my pantry")])
        res = WorkflowInput.model_validate(c)
        assert res.message == "Please plan dinner for this week using my pantry"
    else:
        print("VertexContent is None")
