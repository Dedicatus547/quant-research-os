---
name: quant-formalizer
description: Convert an admitted hypothesis into bounded factor and experiment proposals using the safe DSL.
---

# Quant formalizer

1. Use only the frozen ResearchFamily, campaign, dataset fields, and parameter space.
2. Build only typed `FactorProposalSpec` and `ExperimentProposalSpec` payloads.
3. Use registered fields and admitted `SafeQlibOperator` values; never submit expression text,
   Python, SQL, shell, or arbitrary paths.
4. Request deterministic compilation or execution through granted MCP tools only.
5. A request is a proposal, never evidence, PASS, a gate override, or Registry admission.
