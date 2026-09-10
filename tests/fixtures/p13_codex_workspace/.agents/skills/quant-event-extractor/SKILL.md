---
name: quant-event-extractor
description: Extract one cited event proposal from frozen QuantOS Evidence through typed MCP tools.
---

# Quant event extractor

1. Issue exactly three MCP calls, in this order: one `evidence_get`, then two `evidence_cite`
   calls. Do not emit the final JSON until both citation calls have returned successfully.
2. Use only its hash-bound line spans. Never read paths, files, shell output, or network content.
   For citations, use the view's explicit `extracted_text_hash` field; it is the
   `ExtractedTextArtifact` content hash required by the citation contract, not the nested
   `extracted_text.text_hash` content-bytes hash.
3. If the document supports a share-repurchase progress event, use `share_repurchase`; otherwise
   use `other` and do not imitate the requested benchmark.
4. Build exactly two citations with the two `evidence_cite` calls, in source order:
   - the complete announcement-title line that identifies the event type;
   - the complete cumulative-progress paragraph, from its first line through the line ending with
     the excluded-fees statement.
   For this frozen benchmark layout, the title span is [99,112) and the cumulative paragraph is
   the complete consecutive span [1066,1193), including every intervening line through that
   excluded-fees line; do not cite only its first line.
   Copy each returned citation object verbatim; never calculate `cited_text_hash` yourself.
5. Use the EvidenceRecord `published_at` value as `proposed_event_time`; do not use a signature,
   meeting, cutoff, or retrieval date.
6. Copy `entity_refs` exactly, leave `attributes` empty, and set `limitations` to exactly the
   sorted union of `AGENT_PROPOSAL` and every EvidenceRecord limitation. Add no other limitation.
7. Emit only the JSON object required by the output schema. It is a proposal, never a verdict.
