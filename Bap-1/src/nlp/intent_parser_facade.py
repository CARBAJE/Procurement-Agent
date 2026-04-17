"""Facade over the IntentParser NLP subsystem.

Exposes a single clean function to the rest of Bap-1, hiding all details
of the underlying NLP module (Ollama models, instructor, ParseResult schema).
If IntentParser is replaced by an HTTP microservice in Phase 3, only this
file changes — nothing else in Bap-1 is affected.

IntentParser is found via:
  - pytest: pythonpath = .. in pytest.ini
  - runtime: sys.path.insert in run.py
"""
from IntentParser import parse_request

from shared.models import BecknIntent


def parse_nl_to_intent(query: str) -> BecknIntent | None:
    """Parse a natural-language procurement query into a BecknIntent.

    Returns None if the query is not recognised as a procurement request
    (e.g. greetings, general questions).
    """
    result = parse_request(query)
    return result.beckn_intent
