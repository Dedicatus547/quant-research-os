---
name: quant-event-extractor
description: Extract one cited event proposal from frozen QuantOS Evidence through typed MCP tools.
---

# Quant event extractor

1. Call `evidence_get` exactly once with the evidence hash supplied by the task.
2. Use only its hash-bound line spans. Never read paths, files, shell output, or network content.
3. If the document supports a share-repurchase progress event, use `share_repurchase`; otherwise
   use `other` and do not imitate the requested benchmark.
4. Build exactly two citations with `evidence_cite`, in source order:
   - the complete announcement-title line that identifies the event type;
   - the complete cumulative-progress paragraph, from its first line through the line ending with
     the excluded-fees statement.
5. Use the EvidenceRecord `published_at` value as `proposed_event_time`; do not use a signature,
   meeting, cutoff, or retrieval date.
6. Copy `entity_refs` exactly, leave `attributes` empty, and retain `AGENT_PROPOSAL` plus every
   EvidenceRecord limitation in sorted order.
7. Emit only the JSON object required by the output schema. It is a proposal, never a verdict.
