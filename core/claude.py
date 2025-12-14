from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

import requests
import re

@dataclass
class LocalMessage:
    """
    Objeto sencillo que imita la interfaz básica de anthropic.types.Message.

    Solo necesitamos:
    - content: lista de bloques de texto [{"type": "text", "text": "..."}]
    - stop_reason: cadena que indica el motivo de parada ("end" o "tool_use").
    """

    content: List[Dict[str, Any]]
    stop_reason: str = "end"


# Alias por si algún código espera el nombre Message
Message = LocalMessage


class Claude:
    """
    Wrapper compatible con la clase original `Claude`, pero usando LM Studio.

    En lugar de llamar a la API de Anthropic, enviamos las peticiones a un
    endpoint local OpenAI-compatible expuesto por LM Studio, por defecto:
        http://localhost:1234/v1/chat/completions
    """

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        # Modelo: prioridad -> argumento -> LOCAL_LLM_MODEL -> CLAUDE_MODEL
        self.model = model or os.getenv("LOCAL_LLM_MODEL") or os.getenv("CLAUDE_MODEL")
        if not self.model:
            raise ValueError(
                "No se ha definido ningún modelo (LOCAL_LLM_MODEL / CLAUDE_MODEL)."
            )

        # URL base del servidor de LM Studio (OpenAI compatible)
        self.base_url = base_url or os.getenv(
            "LOCAL_LLM_BASE_URL", "http://localhost:1234/v1"
        )

        # LM Studio no necesita realmente API key, pero dejamos un valor dummy
        self.api_key = api_key or os.getenv("LOCAL_LLM_API_KEY", "not-needed")
        
    def strip_thinking(self, text: str) -> str:
        """
        Elimina bloques [THINK]...[/THINK] que devuelven
        algunos modelos reasoning de LM Studio.
        """
        # Quita cualquier cosa entre [THINK] y [/THINK], en modo multilinea
        cleaned = re.sub(r"\[THINK\].*?\[/THINK\]", "", text, flags=re.DOTALL)
        # Limpia espacios en blanco sobrantes
        return cleaned.strip()

    # ------------------------------------------------------------------
    # Métodos de ayuda para mantener la misma interfaz que la clase original
    # ------------------------------------------------------------------
    def add_user_message(
        self,
        messages: list,
        message: Union[LocalMessage, str, Dict[str, Any]],
    ) -> None:
        """
        Añade un mensaje de usuario a la lista `messages`.
        `message` puede ser otro LocalMessage o simplemente un string.
        """
        content = self._coerce_to_text(message)
        messages.append({"role": "user", "content": content})

    def add_assistant_message(
        self,
        messages: list,
        message: Union[LocalMessage, str, Dict[str, Any]],
    ) -> None:
        """Añade un mensaje del asistente a la lista `messages`."""
        content = self._coerce_to_text(message)
        messages.append({"role": "assistant", "content": content})

    def text_from_message(self, message: LocalMessage) -> str:
        """Extrae texto plano de un LocalMessage y limpia [THINK] si existe.

        Incluimos cualquier bloque que tenga campo 'text', sin importar su 'type'
        (sirve para bloques de documentos, tool_results, etc.).
        """
        if isinstance(message.content, list):
            parts: list[str] = []
            for block in message.content:
                if isinstance(block, dict):
                    # Si el bloque trae texto, lo usamos
                    if "text" in block:
                        parts.append(str(block.get("text", "")))
                    else:
                        # Como fallback, representamos el bloque en crudo
                        parts.append(str(block))
                elif isinstance(block, str):
                    parts.append(block)
            raw = "\n".join(parts)
        elif isinstance(message.content, str):
            raw = message.content
        else:
            raw = str(message.content)

        return self.strip_thinking(raw)

    # ------------------------------------------------------------------
    # Método principal de chat (firma compatible con core.chat.Chat)
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None,
        temperature: float = 1.0,
        stop_sequences: Optional[List[str]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        thinking: bool = False,
        thinking_budget: int = 1024,
    ) -> LocalMessage:
        """
        Envía el historial de mensajes al modelo local de LM Studio.

        Ignoramos por ahora:
        - `tools`: no hacemos tool calling automático.
        - `thinking` y `thinking_budget`: eran específicos de Anthropic.
        """
        stop_sequences = stop_sequences or []

        oa_messages: List[Dict[str, str]] = []

        if system:
            oa_messages.append({"role": "system", "content": system})

        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            content_text = self._message_content_to_text(content)
            oa_messages.append({"role": role, "content": content_text})

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": oa_messages,
            "temperature": float(temperature),
        }

        if stop_sequences:
            payload["stop"] = stop_sequences

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=300,
        )
        response.raise_for_status()
        data = response.json()

        # Respuesta OpenAI-style
        choice = data["choices"][0]
        text = choice["message"]["content"]
        finish_reason = choice.get("finish_reason", "stop")

        content_blocks = [{"type": "text", "text": text}]

        # Mapeamos finish_reason a algo parecido a Anthropic
        stop_reason = (
            "tool_use"
            if finish_reason in {"tool_calls", "function_call"}
            else "end"
        )

        return LocalMessage(content=content_blocks, stop_reason=stop_reason)

    # ------------------------------------------------------------------
    # Utilidades internas
    # ------------------------------------------------------------------
    def _coerce_to_text(
        self,
        message: Union[LocalMessage, str, Dict[str, Any]],
    ) -> str:
        """Convierte un `LocalMessage` u otros formatos simples a texto plano."""
        if isinstance(message, LocalMessage):
            return self.text_from_message(message)
        if isinstance(message, dict):
            if message.get("type") == "text":
                return message.get("text", "")
            return str(message)
        return str(message)

    def _message_content_to_text(self, content: Any) -> str:
        """Normaliza el campo `content` de los mensajes a un string.

        - Si es lista: concatenamos todos los bloques que tengan 'text',
          sin importar el tipo ('text', 'document', 'tool_result', etc.).
        - Si es dict: usamos 'text' si existe; si no, lo convertimos a str.
        """
        if isinstance(content, str):
            return content

        if isinstance(content, dict):
            if "text" in content:
                return str(content.get("text", ""))
            return str(content)

        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if "text" in block:
                        text_parts.append(str(block.get("text", "")))
                    else:
                        text_parts.append(str(block))
                elif isinstance(block, str):
                    text_parts.append(block)
            if text_parts:
                return "\n".join(text_parts)

        return str(content)
