"""Event backbone for Finnovault.

This app provides a single, consistent pipeline:

Data In → Decide → Act → Record → Notify → Learn

It is intentionally lightweight:
- Persist DomainEvent rows (system-of-record)
- Synchronously dispatch handlers in-process (best effort)
"""
