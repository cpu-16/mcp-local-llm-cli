import sys
import asyncio
from typing import Optional, Any
from contextlib import AsyncExitStack

import json
from pydantic import AnyUrl
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client


class MCPClient:
    def __init__(
        self,
        command: str,
        args: list[str],
        env: Optional[dict] = None,
    ):
        self._command = command
        self._args = args
        self._env = env
        self._session: Optional[ClientSession] = None
        self._exit_stack: AsyncExitStack = AsyncExitStack()

    async def connect(self):
        """Arranca el servidor MCP y abre una ClientSession."""
        server_params = StdioServerParameters(
            command=self._command,
            args=self._args,
            env=self._env,
        )

        # stdio_client devuelve (read, write)
        stdio_transport = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read, write = stdio_transport

        # Creamos la sesión MCP de alto nivel
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()

    def session(self) -> ClientSession:
        """Devuelve la sesión activa o lanza error si no estamos conectados."""
        if self._session is None:
            raise ConnectionError(
                "Client session not initialized. "
                "Usa 'await connect()' o el contexto 'async with MCPClient(...)'."
            )
        return self._session

    async def read_resource(self, uri: str) -> Any:
        """
        Lee un recurso MCP (por ejemplo:
        - 'docs://documents'
        - 'docs://documents/report.pdf'

        Devuelve:
        - dict/list si el mimeType es 'application/json'
        - str si es texto plano
        """
        result = await self.session().read_resource(AnyUrl(uri))
        if not result.contents:
            return None

        resource = result.contents[0]

        if isinstance(resource, types.TextResourceContents):
            if resource.mimeType == "application/json":
                return json.loads(resource.text)
            return resource.text

        # Otros tipos de contenido se podrían manejar más adelante
        return getattr(resource, "text", resource)

    # ------------------------------------------------------------------
    # TOOLS
    # ------------------------------------------------------------------
    async def list_tools(self) -> list[types.Tool]:
        """
        Lista las herramientas expuestas por el servidor MCP.

        Soporta dos formas de retorno de la librería:
        - session.list_tools() -> list[Tool]
        - session.list_tools() -> ListToolsResult(tools=[...])
        """
        result = await self.session().list_tools()

        if isinstance(result, list):
            return result  # ya es list[Tool]

        tools = getattr(result, "tools", None)
        if tools is not None:
            return list(tools)

        return []

    async def call_tool(
        self,
        tool_name: str,
        tool_input: dict,
    ) -> types.CallToolResult | None:
        """
        Ejecuta una herramienta en el servidor MCP.

        `tool_input` debe coincidir con los parámetros definidos en el servidor.
        """
        result = await self.session().call_tool(
            tool_name,
            arguments=tool_input,
        )
        return result
    # ------------------------------------------------------------------
    # PROMPTS
    # ------------------------------------------------------------------
    async def list_prompts(self) -> list[types.Prompt]:
        """
        Lista los prompts definidos en el servidor MCP.
        """
        result = await self.session().list_prompts()

        # Algunas versiones pueden devolver directamente list[Prompt]
        if isinstance(result, list):
            return result

        prompts = getattr(result, "prompts", None)
        if prompts is not None:
            return list(prompts)

        return []

    async def get_prompt(self, prompt_name: str, args: dict[str, str]):
        """
        Obtiene un prompt del servidor MCP.

        Normalmente el servidor devuelve un objeto con .messages,
        que es lo que se envía al modelo. Para ser flexible, si no
        existe .messages devolvemos el resultado crudo.
        """
        result = await self.session().get_prompt(
            prompt_name,
            arguments=args,
        )

        # Estilo "guía MCP": devolver los mensajes directamente
        messages = getattr(result, "messages", None)
        if messages is not None:
            return messages

        # Fallback por si la versión de la librería es distinta
        return result

    # ------------------------------------------------------------------
    # RESOURCES
    # ------------------------------------------------------------------

    # CICLO DE VIDA
    # ------------------------------------------------------------------
    async def cleanup(self):
        await self._exit_stack.aclose()
        self._session = None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()


# Test rápido cuando ejecutas este archivo directamente
async def main():
    async with MCPClient(
        # Si no usas uv, cambia a command="python" y ajusta args.
        command="uv",
        args=["run", "mcp_server.py"],
    ) as client:
        print("Connected to MCP server\n")

        tools = await client.list_tools()
        print("Available tools:")
        for tool in tools:
            print(f"- {tool.name}: {getattr(tool, 'description', '')}")

        # Probar read_doc_contents si existe
        if any(t.name == "read_doc_contents" for t in tools):
            print("\nCalling read_doc_contents('report.pdf')...")
            result = await client.call_tool(
                "read_doc_contents",
                {"doc_id": "report.pdf"},
            )
            print("Tool raw result:", result)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
