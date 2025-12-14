import asyncio
import json
import os
import re
from typing import Any

from dotenv import load_dotenv

from core.claude import Claude
from mcp_client import MCPClient
from mcp import types


def extract_json_from_text(text: str) -> str:
    """
    Extrae un bloque JSON de un texto.
    - Si viene como ```json { ... } ``` lo saca de ahí.
    - Si no, devuelve el texto tal cual (strip).
    """
    stripped = text.strip()

    # Buscar bloque ```json ... ```
    m = re.search(r"```json\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Buscar bloque ``` ... ```
    m = re.search(r"```\s*(\{.*\})\s*```", stripped, re.DOTALL)
    if m:
        return m.group(1).strip()

    # Si no hay fences, devolvemos el texto limpio
    return stripped


def build_tools_description(tools: list[types.Tool]) -> str:
    """
    Construye una descripción textual de las herramientas MCP disponibles.
    """
    parts: list[str] = []
    for t in tools:
        desc = getattr(t, "description", "") or ""
        parts.append(f"- {t.name}: {desc}")
    return "\n".join(parts)


def extract_tool_result_text(result: Any) -> str:
    """
    Extrae texto útil de CallToolResult.
    """
    if isinstance(result, types.CallToolResult):
        if isinstance(result.structuredContent, dict) and "result" in result.structuredContent:
            return str(result.structuredContent["result"])

        if result.content:
            for c in result.content:
                if isinstance(c, types.TextContent):
                    return c.text
            return str(result.content)

        return str(result)

    return str(result)


async def chat_with_tools():
    # 1) Cargar variables de entorno (.env)
    load_dotenv()

    # 2) Crear cliente MCP (levanta mcp_server.py con uv)
    async with MCPClient(
        command="uv",
        args=["run", "mcp_server.py"],
    ) as mcp_client:
        print("✅ Conectado al servidor MCP")

        # 3) Listar herramientas disponibles
        tools = await mcp_client.list_tools()
        tools_description = build_tools_description(tools)
        print("🔧 Herramientas MCP disponibles:")
        for t in tools:
            print(f"  - {t.name}")

        # 4) Crear el cliente del modelo local
        model_name = os.getenv("LOCAL_LLM_MODEL") or os.getenv("CLAUDE_MODEL") or "mistralai/minstral-3-14b-reasoning"
        claude = Claude(model=model_name)

        system_prompt = f"""
Eres un asistente que puede llamar herramientas externas a través de JSON.

Tienes acceso a estas herramientas:

{tools_description}

Protocolo de respuesta OBLIGATORIO:
- Si quieres usar una herramienta, responde ÚNICAMENTE con un JSON de este estilo:
  {{"tool": "<nombre_de_la_herramienta>", "arguments": {{ ... }}}}

  Ejemplo:
  {{"tool": "read_doc_contents", "arguments": {{"doc_id": "report.pdf"}}}}

- Si ya tienes la respuesta final para el usuario, responde ÚNICAMENTE con:
  {{"answer": "<tu respuesta en español para el usuario>"}}

- NO mezcles texto fuera del JSON.
- NO expliques el JSON.
- NO añadas comentarios.
- NO uses bloques de código como ```json``` ni otros; responde solo con JSON plano.
Solo JSON válido.
""".strip()

        print("\nEscribe tu pregunta. Comandos: 'salir' o 'exit' para terminar.\n")

        while True:
            user_input = input("> ").strip()
            if not user_input:
                continue

            if user_input.lower() in {"salir", "exit", "quit"}:
                print("👋 Saliendo.")
                break

            # --------- Paso 1: el modelo decide si usa herramienta ---------
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ]
            first_response = claude.chat(messages=messages, temperature=0.0)
            raw_text = claude.text_from_message(first_response)

            # Limpiar fences tipo ```json ...
            clean_text = extract_json_from_text(raw_text)

            # Intentar parsear como JSON
            try:
                obj = json.loads(clean_text)
            except json.JSONDecodeError:
                print("\n[Modelo respondió sin JSON válido. Respuesta cruda:]\n")
                print(raw_text)
                print("\n[Intenté parsear esto como JSON:]\n")
                print(clean_text)
                print()
                continue

            # Si devuelve answer directamente, respondemos al usuario
            if isinstance(obj, dict) and "answer" in obj and "tool" not in obj:
                print("\n[Respuesta del modelo]\n")
                print(obj["answer"])
                print()
                continue

            # Si devuelve tool, ejecutamos herramienta una vez
            if isinstance(obj, dict) and "tool" in obj:
                tool_name = obj["tool"]
                arguments = obj.get("arguments", {}) or {}

                # 🔧 Normalizar argumentos para edit_document
                if tool_name == "edit_document":
                    # Aceptar variantes mal escritas
                    if "old_str" not in arguments:
                        if "old_string" in arguments:
                            arguments["old_str"] = arguments.pop("old_string")
                        elif "old" in arguments:
                            arguments["old_str"] = arguments.pop("old")
                    if "new_str" not in arguments:
                        if "new_string" in arguments:
                            arguments["new_str"] = arguments.pop("new_string")
                        elif "new_striing" in arguments:
                            arguments["new_str"] = arguments.pop("new_striing")
                        elif "new" in arguments:
                            arguments["new_str"] = arguments.pop("new")

                print(f"\n⚙️ El modelo pidió usar la herramienta: {tool_name} con args={arguments}")

                try:
                    tool_result = await mcp_client.call_tool(tool_name, arguments)
                except Exception as e:
                    print(f"\n❌ Error al llamar la herramienta {tool_name}: {e}\n")
                    continue

                tool_text = extract_tool_result_text(tool_result)
                print(f"\n📄 Resultado de la herramienta {tool_name}:\n{tool_text}\n")

                # --------- Paso 2: respuesta final con el resultado ---------
                followup_system = "Eres un asistente que responde en español de forma clara y directa."
                followup_user = (
                    "Pregunta original del usuario:\n"
                    f"{user_input}\n\n"
                    f"Resultado de la herramienta '{tool_name}':\n"
                    f"{tool_text}\n\n"
                    "Usa este resultado para responder al usuario. No vuelvas a usar herramientas. "
                    "Responde SOLO con texto natural en español, sin JSON."
                )

                followup_messages = [
                    {"role": "system", "content": followup_system},
                    {"role": "user", "content": followup_user},
                ]

                second_response = claude.chat(messages=followup_messages, temperature=0.0)
                answer_text = claude.text_from_message(second_response)

                print("\n[Respuesta final]\n")
                print(answer_text)
                print()
                continue

            # Si llega aquí, el JSON no tiene ni answer ni tool
            print("\n[El modelo devolvió JSON pero sin 'answer' ni 'tool']\n")
            print(obj)
            print()


if __name__ == "__main__":
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(chat_with_tools())
