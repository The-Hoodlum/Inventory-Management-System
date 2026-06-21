"""Conversational assistant (WhatsApp/OpenAI).

Answers natural-language questions about inventory, sales, and procurement via OpenAI
function-calling. The model NEVER touches the database: it can only call the vetted
read tools in ``domain/tools.py``, which run through the repository (RLS- and
branch-scoped). The channel (WhatsApp vs the local API) is abstracted behind
``whatsapp.WhatsAppAdapter`` so the same engine serves both.
"""
