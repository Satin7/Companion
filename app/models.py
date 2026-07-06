from pydantic import BaseModel
from typing import Dict, Any, Optional


class StartSessionRequest(BaseModel):
    user_id: str
    metadata: Optional[Dict[str, Any]] = None


class TriggerCondition(BaseModel):
    type: str
    params: Dict[str, Any] = {}


class TriggerAction(BaseModel):
    type: str
    params: Dict[str, Any] = {}


class TriggerRequest(BaseModel):
    user_id: str
    condition: TriggerCondition
    action: TriggerAction
