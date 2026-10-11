---
name: protocol-retrieval
description: Retrieve reference clinical protocols strictly bound to canonical LOINC URIs. Never aggregate data across multiple distinct URIs.
license: Apache-2.0
metadata:
  roles: protocol_retriever
  risk_class: clinical
  bundle_sha256: pending
---

# Protocol Retrieval

This skill guides the protocol retriever in pulling clinical reference protocols.

## Invariants

1. Call `fetch_grounded_protocol` using only the validated, canonical LOINC URI provided by the safety gate.
2. Return the exact reference bounds, panic limits, and governing guideline metadata returned by the tool.
3. Never aggregate, interpolate, or blend values from multiple distinct URIs into one protocol response.
4. Refuse requests lacking a valid canonical URI.
