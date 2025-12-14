import asyncio
import sys
import os
from dotenv import load_dotenv
from contextlib import AsyncExitStack

from mcp_client import MCPClient
from core.claude import Claude

from core.cli_chat import CliChat
from core.cli import CliApp

# Carga variables de entorno desde .env
load_dotenv()

# Configuración del modelo local (LM Studio)
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "")
LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:1234/v1")

assert LOCAL_LLM_MODEL, "Error: LOCAL_LLM_MODEL no puede estar vacío. Actualiza tu archivo .env"


async def main() -> None:
    # Instanciamos el wrapper que habla con el modelo local
    claude_service = Claude(
        model=LOCAL_LLM_MODEL,
        base_url=LOCAL_LLM_BASE_URL,
    )

    server_scripts = sys.argv[1:]
    clients: dict[str, MCPClient] = {}

    # Elegir cómo lanzar el servidor MCP principal (con uv o con python)
    command, args = (
        ("uv", ["run", "mcp_server.py"])
        if os.getenv("USE_UV", "0") == "1"
        else ("python", ["mcp_server.py"])
    )

    async with AsyncExitStack() as stack:
        # Cliente principal para leer documentos/prompts
        doc_client = await stack.enter_async_context(
            MCPClient(command=command, args=args)
        )
        clients["doc_client"] = doc_client

        # Clientes adicionales para otros servidores MCP que pases por línea de comandos
        for i, server_script in enumerate(server_scripts):
            client_id = f"client_{i}_{server_script}"
            client = await stack.enter_async_context(
                MCPClient(command="uv", args=["run", server_script])
            )
            clients[client_id] = client

        chat = CliChat(
            doc_client=doc_client,
            clients=clients,
            claude_service=claude_service,
        )

        cli = CliApp(chat)
        await cli.initialize()
        await cli.run()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
