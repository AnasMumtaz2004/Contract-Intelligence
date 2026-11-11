# Data

## Real contracts
`cuad_subset/` holds a sample of the Contract Understanding Atticus Dataset (CUAD) v1.
CUAD is by The Atticus Project and is licensed under CC BY 4.0.
Source: https://www.atticusprojectai.org/cuad

## Synthetic data (generated for software testing)
These files are NOT real contracts. They are made by scripts in `eval/`.

- `synthetic/amendments/` : fake amendments to CUAD contracts. The change is chosen in code,
  an LLM only rewrites the clause wording, and `manifest.json` records every change.
- `synthetic/scanned/` : CUAD contracts turned into noisy page images, to test OCR.

Questions for the evaluation are in `eval/questions*.jsonl`.
Levels 1, 2 and 7 come from CUAD labels. Level 3 uses an LLM to write the question.
Levels 4 and 6 come from CUAD text and labels. Level 5 comes from the amendment manifest.
Every question was checked by hand.