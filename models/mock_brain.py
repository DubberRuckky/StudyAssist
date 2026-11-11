"""MockBrain implementation for offline testing, verification, and isolation checks."""

from typing import Any, Callable, Dict, List, Optional


class MockBrain:
    """Offline test brain that records calls and returns scripted or synthesized replies."""

    def __init__(self) -> None:
        """Initialize mock brain with call histories and response queues."""
        self.call_history: List[Dict[str, Any]] = []
        self.scripted_replies: List[Dict[str, Any]] = []
        self.default_reply_generator: Optional[Callable[[List[Dict[str, str]]], Dict[str, Any]]] = None

    def reset(self) -> None:
        """Reset the call history and queued scripted responses."""
        self.call_history.clear()
        self.scripted_replies.clear()
        self.default_reply_generator = None

    def queue_reply(self, reply: Dict[str, Any]) -> None:
        """Queue a scripted response to be returned on the next chat call."""
        self.scripted_replies.append(reply)

    def set_reply_generator(self, generator: Callable[[List[Dict[str, str]]], Dict[str, Any]]) -> None:
        """Set a dynamic generator function to produce responses based on input messages."""
        self.default_reply_generator = generator

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute mock chat call, record interaction details, and return a canned response."""
        record = {
            "messages": [dict(m) for m in messages],
            "tools": tools,
            "options": options or {},
        }
        self.call_history.append(record)

        # Check if there is an explicit scripted reply
        if self.scripted_replies:
            return self.scripted_replies.pop(0)

        # Check if there is a custom reply generator
        if self.default_reply_generator:
            return self.default_reply_generator(messages)

        # Default fallback response for agent / portable mode or general chat
        last_message = messages[-1].get("content", "") if messages else ""
        
        # If tools are requested and portable mode instructions are present, simulate a final or tool response
        if tools and "action" in last_message.lower():
            # If the user asked to search or ingest, return mock tool call or final answer
            return {
                "content": '{"action": "final", "answer": "MockBrain final verified answer."}',
                "tool_calls": [],
                "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
            }

        return {
            "content": "MockBrain response for: " + (last_message[:50] if last_message else "empty prompt"),
            "tool_calls": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }


# Global test instance for mock testing
_GLOBAL_MOCK_BRAIN = MockBrain()


def get_mock_brain() -> MockBrain:
    """Return the global MockBrain instance used during testing."""
    return _GLOBAL_MOCK_BRAIN
