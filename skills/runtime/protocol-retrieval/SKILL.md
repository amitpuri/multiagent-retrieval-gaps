---
name: protocol-retrieval
description: Retrieve the protocol bound to one resolved LOINC URI. Use only after the safety gate routed the query to PROCEED; refuse requests without a resolved URI and never combine protocols from different URIs.
allowed-tools: fetch_grounded_protocol
license: Apache-2.0
metadata:
  roles: protocol_retriever
  risk_class: clinical
  version: 1.0.0
---

# Protocol retrieval

## Steps

1. Call `fetch_grounded_protocol` with the single resolved URI from the gate result.
2. Return the tool result unchanged, including trust tier, lifecycle status
   and review date.

## Rules

- Refuse a request that carries no resolved URI, or more than one.
- Never aggregate, average or interpolate protocol data across URIs.
- Never add protocol content from memory or general knowledge.
