"""
Unified LLM Manager - Supports multiple LLM providers (DeepSeek API + Local Gemma3 via Ollama).
Routes queries to the appropriate provider and handles fallback logic.
"""

import os
import json
import logging
import hashlib
import asyncio
import time
from enum import Enum
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import requests

from app.utils.prompts import SYSTEM_PROMPT

load_dotenv()

logger = logging.getLogger(__name__)

# Cache configuration
_query_cache: Dict[str, str] = {}
_MAX_CACHE_SIZE = 100


class LLMProvider(str, Enum):
    """Supported LLM providers"""
    DEEPSEEK = "deepseek"
    GEMMA3 = "gemma3"


class LLMManager:
    """
    Unified interface for querying multiple LLM providers.
    Handles provider selection, fallback logic, and response normalization.
    """

    def __init__(self):
        """Initialize LLM Manager with provider configurations"""
        # Default provider (can be overridden at query time)
        default_provider_str = os.getenv("DEFAULT_LLM_PROVIDER", "DEEPSEEK").upper()
        try:
            self.default_provider = LLMProvider[default_provider_str]
        except KeyError:
            logger.warning(f"Invalid DEFAULT_LLM_PROVIDER: {default_provider_str}, using DEEPSEEK")
            self.default_provider = LLMProvider.DEEPSEEK

        # DeepSeek configuration
        self.deepseek_api_key = os.getenv("DEEPSEEK_API_KEY")
        self.deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.deepseek_url = "https://api.deepseek.com/v1/chat/completions"
        self.deepseek_timeout = 30

        # Ollama configuration
        self.ollama_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "gemma3:4b")
        self.ollama_timeout = int(os.getenv("OLLAMA_TIMEOUT", "60"))

        # Fallback settings
        self.enable_fallback = os.getenv("ENABLE_LLM_FALLBACK", "true").lower() == "true"

        logger.info(f"LLMManager initialized with default provider: {self.default_provider.value}")
        logger.info(f"Ollama endpoint: {self.ollama_url}")
        logger.info(f"Ollama model: {self.ollama_model}")
        logger.info(f"DeepSeek model: {self.deepseek_model}")

    async def query_llm(
        self,
        prompt: str,
        provider: Optional[LLMProvider] = None,
        context: Optional[Dict[str, Any]] = None,
        user_location: Optional[Dict[str, float]] = None,
        query_type: Optional[str] = None,
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Query the appropriate LLM provider with automatic fallback support.

        Args:
            prompt: The user's natural language query
            provider: Specific provider to use (defaults to self.default_provider)
            context: Optional context information
            user_location: Optional user GPS coordinates {'lat': float, 'lon': float}
            query_type: Optional query type hint ('spatial', 'stats', 'raster')
            system_prompt: Optional custom system prompt (defaults to SYSTEM_PROMPT)

        Returns:
            Raw text response from LLM

        Raises:
            Exception: If query fails and fallback is disabled, or both providers fail
        """
        provider = provider or self.default_provider

        try:
            if provider == LLMProvider.GEMMA3:
                logger.info("🤖 Using Gemma3 (local)")
                return await self._query_ollama(prompt, context, user_location, query_type, system_prompt)
            elif provider == LLMProvider.DEEPSEEK:
                logger.info("🧠 Using DeepSeek API")
                return self._query_deepseek(prompt, context, user_location, query_type, system_prompt)
            else:
                raise ValueError(f"Unknown provider: {provider}")

        except Exception as e:
            logger.error(f"Error querying {provider.value}: {e}")

            # Fallback logic
            if self.enable_fallback and provider == LLMProvider.GEMMA3:
                logger.warning("⚠️ Gemma3 failed, falling back to DeepSeek...")
                try:
                    return self._query_deepseek(prompt, context, user_location, query_type)
                except Exception as fallback_error:
                    logger.error(f"Fallback to DeepSeek also failed: {fallback_error}")
                    raise fallback_error

            raise

    async def _query_ollama(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        user_location: Optional[Dict[str, float]] = None,
        query_type: Optional[str] = None,
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Query Ollama API (OpenAI-compatible endpoint).

        Args:
            prompt: The user's natural language query
            context: Optional context information
            user_location: Optional user GPS coordinates
            query_type: Optional query type hint
            system_prompt: Optional custom system prompt

        Returns:
            Raw text response from Ollama
        """
        # Check cache first
        cache_context = {}
        if context:
            cache_context.update(context)
        if user_location:
            cache_context["user_location"] = user_location
        if query_type:
            cache_context["query_type"] = query_type

        cache_key = self._generate_cache_key(prompt, cache_context if cache_context else None)
        if cache_key in _query_cache:
            logger.info("💨 Cache hit! Returning cached response")
            return _query_cache[cache_key]

        # Build the full prompt
        full_prompt = self._build_full_prompt(prompt, context, user_location, query_type)

        # Use provided system prompt or fallback to default
        effective_system_prompt = system_prompt or SYSTEM_PROMPT

        # Prepare payload (OpenAI-compatible format)
        payload = {
            "model": self.ollama_model,
            "messages": [
                {"role": "system", "content": effective_system_prompt},
                {"role": "user", "content": full_prompt}
            ],
            "temperature": 0,  # Deterministic for SQL generation
            "stream": False
        }

        try:
            logger.info(f"🤖 Querying Ollama ({self.ollama_model})...")

            # Make async request
            response = await self._async_post(
                f"{self.ollama_url}/api/chat",
                json=payload,
                timeout=self.ollama_timeout
            )

            if response.status_code != 200:
                raise Exception(f"Ollama API error: {response.status_code} - {response.text}")

            result = response.json()
            content = result["message"]["content"]

            # Cache the response
            if len(_query_cache) >= _MAX_CACHE_SIZE:
                _query_cache.clear()
            _query_cache[cache_key] = content

            logger.info(f"✅ Ollama response received ({len(content)} chars)")
            return content

        except asyncio.TimeoutError:
            raise Exception("Ollama request timeout. The model may be processing a complex query.")
        except Exception as e:
            logger.error(f"Ollama API request failed: {e}")
            raise

    def _query_deepseek(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        user_location: Optional[Dict[str, float]] = None,
        query_type: Optional[str] = None,
        system_prompt: Optional[str] = None
    ) -> str:
        """
        Query DeepSeek API (HTTP POST).

        Args:
            prompt: The user's natural language query
            context: Optional context information
            user_location: Optional user GPS coordinates
            query_type: Optional query type hint
            system_prompt: Optional custom system prompt

        Returns:
            Raw text response from DeepSeek
        """
        if not self.deepseek_api_key:
            raise ValueError("DEEPSEEK_API_KEY not found in environment variables")

        # Check cache first
        cache_context = {}
        if context:
            cache_context.update(context)
        if user_location:
            cache_context["user_location"] = user_location
        if query_type:
            cache_context["query_type"] = query_type

        cache_key = self._generate_cache_key(prompt, cache_context if cache_context else None)
        if cache_key in _query_cache:
            logger.info("💨 Cache hit! Returning cached response")
            return _query_cache[cache_key]

        # Build the full prompt
        full_prompt = self._build_full_prompt(prompt, context, user_location, query_type)

        # Use provided system prompt or fallback to default
        effective_system_prompt = system_prompt or SYSTEM_PROMPT

        payload = {
            "model": self.deepseek_model,
            "messages": [
                {"role": "system", "content": effective_system_prompt},
                {"role": "user", "content": full_prompt}
            ],
            "temperature": 0,  # Deterministic for SQL generation
            "max_tokens": 1500
        }

        try:
            logger.info(f"🧠 Querying DeepSeek ({self.deepseek_model})...")

            response = requests.post(
                self.deepseek_url,
                headers={
                    "Authorization": f"Bearer {self.deepseek_api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=self.deepseek_timeout
            )
            response.raise_for_status()

            result = response.json()
            content = result["choices"][0]["message"]["content"]

            # Cache the response
            if len(_query_cache) >= _MAX_CACHE_SIZE:
                _query_cache.clear()
            _query_cache[cache_key] = content

            logger.info(f"✅ DeepSeek response received ({len(content)} chars)")
            return content

        except requests.exceptions.Timeout:
            raise Exception("DeepSeek API timeout. Please try a simpler query.")
        except requests.exceptions.RequestException as e:
            raise Exception(f"DeepSeek API request failed: {str(e)}")
        except (KeyError, IndexError) as e:
            raise Exception(f"Unexpected response format from DeepSeek: {str(e)}")

    async def _async_post(self, url: str, json: Dict = None, timeout: int = 30) -> requests.Response:
        """
        Make async HTTP POST request.

        Args:
            url: Target URL
            json: JSON payload
            timeout: Request timeout in seconds

        Returns:
            Response object
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: requests.post(url, json=json, timeout=timeout)
        )

    def _build_full_prompt(
        self,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
        user_location: Optional[Dict[str, float]] = None,
        query_type: Optional[str] = None
    ) -> str:
        """
        Build the full prompt with context and user location information.

        Args:
            prompt: Base user query
            context: Optional context
            user_location: Optional GPS coordinates
            query_type: Optional query type hint

        Returns:
            Full prompt string
        """
        full_prompt = prompt

        if query_type:
            full_prompt = f"{full_prompt}\n\nQuery type: {query_type}"

        if user_location:
            full_prompt = f"{full_prompt}\n\nuser_location: {{lat: {user_location.get('lat')}, lon: {user_location.get('lon')}}}"

        if context:
            full_prompt = f"{full_prompt}\n\nContext: {json.dumps(context)}"

        return full_prompt

    def _generate_cache_key(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Generate a unique cache key for a query.

        Args:
            prompt: User query
            context: Optional context

        Returns:
            Cache key string
        """
        cache_str = prompt.lower().strip()
        if context:
            cache_str += json.dumps(context, sort_keys=True)
        return hashlib.md5(cache_str.encode()).hexdigest()

    def get_model_name(self, provider: Optional[LLMProvider] = None) -> str:
        """
        Get the model name for a provider.

        Args:
            provider: LLM provider (defaults to default_provider)

        Returns:
            Model name string
        """
        provider = provider or self.default_provider
        if provider == LLMProvider.DEEPSEEK:
            return self.deepseek_model
        elif provider == LLMProvider.GEMMA3:
            return self.ollama_model
        return "unknown"

    def check_provider_health(self, provider: LLMProvider) -> bool:
        """
        Check if a provider is accessible.

        Args:
            provider: LLM provider to check

        Returns:
            True if provider is healthy, False otherwise
        """
        try:
            if provider == LLMProvider.DEEPSEEK:
                # Check if API key is configured
                return bool(self.deepseek_api_key)
            elif provider == LLMProvider.GEMMA3:
                # Check if Ollama server is running
                response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
                return response.status_code == 200
        except Exception as e:
            logger.debug(f"Provider health check failed for {provider.value}: {e}")
            return False

    async def list_available_models(self) -> Dict[str, list]:
        """
        List available models for each provider.

        Returns:
            Dictionary with provider names as keys and list of models as values
        """
        models = {}

        # Ollama models
        try:
            response = await self._async_post(
                f"{self.ollama_url}/api/tags",
                timeout=5
            )
            if response.status_code == 200:
                ollama_data = response.json()
                models["gemma3"] = [
                    model["name"] for model in ollama_data.get("models", [])
                ]
        except Exception as e:
            logger.warning(f"Could not list Ollama models: {e}")
            models["gemma3"] = []

        # DeepSeek (no public list, but we know the models)
        models["deepseek"] = [self.deepseek_model]

        return models


# Global instance
_llm_manager: Optional[LLMManager] = None


def get_llm_manager() -> LLMManager:
    """
    Get or create the global LLMManager instance.

    Returns:
        LLMManager instance
    """
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMManager()
    return _llm_manager
