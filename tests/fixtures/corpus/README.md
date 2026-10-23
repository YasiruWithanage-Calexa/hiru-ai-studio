# Fixture corpus: "Harbour Lights"

Invented sample production used by the ingestion tests and the retrieval evaluation
(`scripts/eval_retrieval.py`, probes in `tests/eval/retrieval_probes.json`). Not Hiru content:
a generic family drama, so nothing is tuned to one story. English action and
description, Sinhala dialogue, as Hiru's scripts are.

Changing these files changes the retrieval baseline: re-run the eval and update
`tests/eval/thresholds.json` in the same commit.
