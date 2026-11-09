## Retrieval only (no LLM): did the right clause reach the model?

| Pipeline | Group | Questions | Context hit | Amendment retrieved |
|---|---|---|---|---|
| naive | level 1 | 11 | 1.00 | - |
| hybrid | level 1 | 11 | 1.00 | - |
| hybrid_rerank | level 1 | 11 | 1.00 | - |
| hybrid_rerank_xref | level 1 | 11 | 1.00 | - |
| naive | level 2 | 11 | 0.82 | - |
| hybrid | level 2 | 11 | 0.64 | - |
| hybrid_rerank | level 2 | 11 | 0.73 | - |
| hybrid_rerank_xref | level 2 | 11 | 0.73 | - |
| naive | level 3 | 2 | 1.00 | - |
| hybrid | level 3 | 2 | 1.00 | - |
| hybrid_rerank | level 3 | 2 | 1.00 | - |
| hybrid_rerank_xref | level 3 | 2 | 1.00 | - |
| naive | level 4 | 4 | 0.75 | - |
| hybrid | level 4 | 4 | 1.00 | - |
| hybrid_rerank | level 4 | 4 | 1.00 | - |
| hybrid_rerank_xref | level 4 | 4 | 1.00 | - |
| naive | level 5 | 7 | 0.86 | 0.75 |
| hybrid | level 5 | 7 | 0.86 | 1.00 |
| hybrid_rerank | level 5 | 7 | 1.00 | 1.00 |
| hybrid_rerank_xref | level 5 | 7 | 1.00 | 1.00 |
| naive | level 6 | 5 | 0.60 | - |
| hybrid | level 6 | 5 | 0.60 | - |
| hybrid_rerank | level 6 | 5 | 0.60 | - |
| hybrid_rerank_xref | level 6 | 5 | 0.60 | - |
| naive | scanned copies | 10 | 0.80 | - |
| hybrid | scanned copies | 10 | 0.80 | - |
| hybrid_rerank | scanned copies | 10 | 0.80 | - |
| hybrid_rerank_xref | scanned copies | 10 | 0.80 | - |

## Questions that have an answer (digital contracts)

| Pipeline | Level | Questions | Context hit | Answered | Faithfulness | Relevancy | Ctx precision | Ctx recall |
|---|---|---|---|---|---|---|---|---|
| naive | 1 | 11 | 1.00 | 1.00 | - | - | - | - |
| naive | 2 | 11 | 0.82 | 0.82 | - | - | - | - |
| naive | 3 | 2 | 1.00 | 1.00 | - | - | - | - |
| naive | 4 | 4 | 0.75 | 1.00 | - | - | - | - |
| naive | 5 | 7 | 0.86 | 1.00 | - | - | - | - |
| hybrid | 5 | 1 | 1.00 | 1.00 | - | - | - | - |
| naive | 6 | 5 | 0.60 | 0.60 | - | - | - | - |

## Amendment questions (level 5, only the ones where an amendment changed the answer)

| Pipeline | Questions | Amendment retrieved | Answer states the current value |
|---|---|---|---|
| naive | 4 | 0.75 | 0.50 |
| hybrid | 1 | 1.00 | 0.00 |

## Questions with no answer in the contract (level 7)

| Pipeline | Questions | Correctly said not found |
|---|---|---|
| naive | 6 | 0.67 |
| hybrid | 5 | 0.80 |
| agentic | 21 | 0.90 |

## Scanned copies (OCR)

| Pipeline | Questions (levels 1-2) | Context hit | Answered | Questions (level 7) | Correctly said not found |
|---|---|---|---|---|---|
| naive | 10 | 0.80 | 0.80 | 3 | 1.00 |

Context hit = share of questions where the retrieved chunks contain the expected clause.
Answered = share of answerable questions where the model gave an answer instead of not found.
Amendment retrieved / current value are free checks from the amendment manifest, no LLM judge.
Ragas scores only cover answers that were actually given.