from pydantic import Field
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base 
# -------------------------------------------------
# Instancia del servidor MCP
# -------------------------------------------------
mcp = FastMCP("DocumentMCP", log_level="ERROR")

# "Base de datos" en memoria de documentos
docs = {
    "deposition.md": "This deposition covers the testimony of Angela Smith, P.E.",
    "report.pdf": "The report details the state of a 20m condenser tower.",
    "financials.docx": "These financials outline the project's budget and expenditures.",
    "outlook.pdf": "This document presents the projected future performance of the system.",
    "plan.md": "The plan outlines the steps for the project's implementation.",
    "spec.txt": "These specifications define the technical requirements for the equipment.",
}

# -------------------------------------------------
# TOOLS (acciones)
# -------------------------------------------------


@mcp.tool(
    name="read_doc_contents",
    description="Read the contents of a document and return it as a string.",
)
def read_document(
    doc_id: str = Field(description="Id of the document to read"),
) -> str:
    """Return the full contents of a document."""
    if doc_id not in docs:
        raise ValueError(f"Doc with id {doc_id} not found")
    return docs[doc_id]


@mcp.tool(
    name="edit_document",
    description=(
        "Edit a document by replacing a string in the document's content "
        "with a new string."
    ),
)
def edit_document(
    doc_id: str = Field(description="Id of the document that will be edited"),
    old_str: str = Field(
        description="The exact text to replace (case and whitespace must match)."
    ),
    new_str: str = Field(
        description="The new text to insert in place of the old text."
    ),
) -> str:
    """Simple find/replace edit on a document."""
    if doc_id not in docs:
        raise ValueError(f"Doc with id {doc_id} not found")

    docs[doc_id] = docs[doc_id].replace(old_str, new_str)
    return docs[doc_id]


# -------------------------------------------------
# RESOURCES (datos tipo GET, solo lectura)
# -------------------------------------------------

# 📚 Recurso 1: lista de IDs de documentos
@mcp.resource(
    "docs://documents",
    mime_type="application/json",
)
def list_docs() -> list[str]:
    """
    Devuelve la lista de IDs de documentos disponibles.
    Ej: ["deposition.md", "report.pdf", ...]
    """
    return list(docs.keys())


# 📄 Recurso 2: contenido de un documento concreto
@mcp.resource(
    "docs://documents/{doc_id}",
    mime_type="text/plain",
)
def fetch_doc(
    doc_id: str = Field(description="Id del documento a leer"),
) -> str:
    """
    Devuelve el contenido del documento indicado por doc_id.
    """
    if doc_id not in docs:
        raise ValueError(f"Doc with id {doc_id} not found")
    return docs[doc_id]


# -------------------------------------------------
# PROMPTS (plantillas de prompts reutilizables)
# -------------------------------------------------

@mcp.prompt(
    name="rewrite_markdown",
    description="Rewrite a document using clear, well-structured Markdown.",
)
def rewrite_doc_markdown(
    doc_id: str = Field(description="Id of the document to rewrite in Markdown"),
) -> str:
    """
    Prompt para reescribir un documento con sintaxis Markdown legible.
    """
    if doc_id not in docs:
        raise ValueError(f"Doc with id {doc_id} not found")

    content = docs[doc_id]
    return (
        "You are an expert technical writer. Rewrite the following document "
        "using clear, well-structured Markdown. Keep the meaning but improve "
        "organization and readability. Use headings, bullet points, and tables "
        "when appropriate.\n\n"
        f"DOCUMENT CONTENT:\n{content}"
    )


@mcp.prompt(
    name="summarize",
    description="Summarize a document in a concise way.",
)
def summarize_doc(
    doc_id: str = Field(description="Id of the document to summarize"),
) -> str:
    """
    Prompt para generar un resumen corto del documento.
    """
    if doc_id not in docs:
        raise ValueError(f"Doc with id {doc_id} not found")

    content = docs[doc_id]
    return (
        "Summarize the following document in a concise paragraph, "
        "highlighting the most important technical and business points:\n\n"
        f"DOCUMENT CONTENT:\n{content}"
    )


@mcp.prompt(
    name="format",
    description="Rewrites the contents of the document in Markdown format.",
)
def format_document(
    doc_id: str = Field(description="Id of the document to format in Markdown"),
) -> str:
    """
    Prompt tipo '/format': formatear el documento en buen Markdown.
    """
    if doc_id not in docs:
        raise ValueError(f"Doc with id {doc_id} not found")

    content = docs[doc_id]

    # Este prompt asume que el modelo ya recibe el CONTENIDO del doc
    # (por recursos o porque el cliente lo inyecta).
    return (
        "Your goal is to reformat a document using clean, professional "
        "Markdown syntax.\n\n"
        "Instructions:\n"
        "- Add clear headings and subheadings with '#', '##', etc.\n"
        "- Use bullet lists and numbered lists where they make sense.\n"
        "- Use code blocks for technical snippets.\n"
        "- Keep the meaning of the document, but improve structure and clarity.\n\n"
        "Here is the document you must reformat:\n\n"
        f"{content}"
    )



# -------------------------------------------------
# Punto de entrada del servidor MCP
# -------------------------------------------------
if __name__ == "__main__":
    # Transport stdio: el cliente MCP (tu CLI / tool_agent) hablará con este
    # proceso por stdin/stdout.
    mcp.run(transport="stdio")
