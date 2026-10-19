"""Tally connector (XML over HTTP). Built from M1; all Tally-specific logic stays here.

The flow: envelopes (requests) -> client (HTTP) -> parser (records) -> mapping (meaning);
connector.py puts them together behind the generic connector interface (connectors/base.py).
"""
