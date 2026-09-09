import asyncio
import copy
from typing import Callable, Any, Dict, List

class HookManager:
    """
    Middleware Hook System for Transparent Tool Augmentation.
    Allows registering callbacks for events like 'tool.execute.before' and 'tool.execute.after'.
    """
    def __init__(self):
        self._hooks: Dict[str, List[Callable]] = {}

    def register(self, event_name: str, callback: Callable) -> None:
        """Register a hook callback for a specific event."""
        if event_name not in self._hooks:
            self._hooks[event_name] = []
        self._hooks[event_name].append(callback)

    async def emit(self, event_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Emit an event and pass the payload through all registered hooks sequentially.
        Ensures payload isolation by using deepcopy where safe.
        """
        # Preserve non-deepcopyable objects
        context = payload.pop("context", None)
        sandbox_manager = payload.pop("sandbox_manager", None)
        
        try:
            current_payload = copy.deepcopy(payload)
        except Exception:
            # Fallback to shallow copy if deepcopy fails
            current_payload = payload.copy()
            
        # Restore objects
        if context: current_payload["context"] = context
        if sandbox_manager: current_payload["sandbox_manager"] = sandbox_manager
        
        for hook in self._hooks.get(event_name, []):
            if asyncio.iscoroutinefunction(hook):
                current_payload = await hook(current_payload)
            else:
                current_payload = hook(current_payload)
                
        return current_payload

