"""
Conversation Manager - Maintains multi-turn conversation history for spatial queries.
Uses DeepSeek's native conversation context for natural pronoun handling and context awareness.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ConversationMessage:
    """Represents a single message in the conversation"""

    def __init__(self, role: str, content: str, metadata: Optional[Dict[str, Any]] = None):
        self.role = role  # "system", "user", "assistant"
        self.content = content
        self.metadata = metadata or {}
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> Dict[str, str]:
        """Convert to API message format"""
        return {
            "role": self.role,
            "content": self.content
        }


class ConversationHistory:
    """
    Maintains full conversation history for a session.
    Passes complete history to DeepSeek for context-aware responses.
    """

    def __init__(self, session_id: str, system_prompt: str):
        self.session_id = session_id
        self.messages: List[ConversationMessage] = []
        self.created_at = datetime.utcnow().isoformat()

        # Add system prompt as first message
        self.messages.append(
            ConversationMessage(
                role="system",
                content=system_prompt,
                metadata={"type": "system_prompt"}
            )
        )

    def add_user_message(self, content: str) -> None:
        """Add a user query to the history"""
        self.messages.append(
            ConversationMessage(
                role="user",
                content=content,
                metadata={"type": "query"}
            )
        )
        logger.info(f"[{self.session_id}] Added user message: {content[:100]}...")

    def add_assistant_message(self, content: str, result_metadata: Optional[Dict[str, Any]] = None) -> None:
        """Add an assistant response to the history"""
        self.messages.append(
            ConversationMessage(
                role="assistant",
                content=content,
                metadata={
                    "type": "response",
                    "result_metadata": result_metadata or {}
                }
            )
        )
        logger.info(f"[{self.session_id}] Added assistant message")

    def get_api_messages(self) -> List[Dict[str, str]]:
        """Get all messages in format suitable for DeepSeek API"""
        return [msg.to_dict() for msg in self.messages]

    def get_full_context(self) -> str:
        """Get readable full conversation context"""
        context_lines = []
        for msg in self.messages:
            if msg.role == "system":
                context_lines.append(f"[SYSTEM]\n{msg.content[:200]}...\n")
            elif msg.role == "user":
                context_lines.append(f"[USER]\n{msg.content}\n")
            elif msg.role == "assistant":
                context_lines.append(f"[ASSISTANT]\n{msg.content[:300]}...\n")
        return "\n".join(context_lines)

    def message_count(self) -> int:
        """Total messages in conversation"""
        return len(self.messages)

    def clear(self) -> None:
        """Clear all messages except system prompt"""
        if self.messages and self.messages[0].role == "system":
            system_msg = self.messages[0]
            self.messages = [system_msg]
        else:
            self.messages = []


class ConversationManager:
    """
    Manages multiple conversation sessions.
    Each user/session gets its own conversation history.
    """

    def __init__(self, max_sessions: int = 100):
        self.sessions: Dict[str, ConversationHistory] = {}
        self.max_sessions = max_sessions

    def create_session(self, session_id: str, system_prompt: str) -> ConversationHistory:
        """Create a new conversation session"""
        # Evict oldest session if at capacity
        if len(self.sessions) >= self.max_sessions:
            oldest_id = min(self.sessions.keys(),
                          key=lambda k: self.sessions[k].created_at)
            logger.warning(f"Evicting oldest session {oldest_id} to stay under max capacity")
            del self.sessions[oldest_id]

        history = ConversationHistory(session_id, system_prompt)
        self.sessions[session_id] = history
        logger.info(f"Created new session: {session_id}")
        return history

    def get_session(self, session_id: str) -> Optional[ConversationHistory]:
        """Get conversation history for a session"""
        return self.sessions.get(session_id)

    def get_or_create_session(self, session_id: str, system_prompt: str) -> ConversationHistory:
        """Get existing session or create new one"""
        if session_id not in self.sessions:
            return self.create_session(session_id, system_prompt)
        return self.sessions[session_id]

    def delete_session(self, session_id: str) -> bool:
        """Delete a conversation session"""
        if session_id in self.sessions:
            del self.sessions[session_id]
            logger.info(f"Deleted session: {session_id}")
            return True
        return False

    def list_sessions(self) -> List[str]:
        """List all active session IDs"""
        return list(self.sessions.keys())

    def clear_all_sessions(self) -> None:
        """Clear all sessions"""
        self.sessions.clear()
        logger.info("Cleared all sessions")


# Global conversation manager instance
_global_manager = ConversationManager()


def get_conversation_manager() -> ConversationManager:
    """Get the global conversation manager"""
    return _global_manager


def reset_conversation_manager() -> None:
    """Reset the global manager (for testing)"""
    global _global_manager
    _global_manager = ConversationManager()
