# Adam: how to

Plan: [plan/2026-11-04b/PLAN.md](../../plan/2026-11-04b/PLAN.md). Status: [IMPLEMENTED.md](../../plan/2026-11-04b/IMPLEMENTED.md).

## Make a new Adam part

```
hiru-ai new agent adam_dramaturg --group adam      # writes src/libs/hiru_ai/agents/adam/adam_dramaturg/
hiru-ai new step adam_write --group adam
hiru-ai list --group adam                          # only Adam's parts
hiru-ai validate                                   # ids, schemas, prompts, evals, the group rules
```

The id must start with `adam_`. Without `--group`, `hiru-ai new` refuses an `adam_` id; `validate` refuses an `adam_` id
outside an `adam/` folder, a part of the group that names a part outside it, and a part outside it that names one inside.

## Remove Adam

```
hiru-ai remove --group adam          # a dry run: the folders that go, then everything outside that still names Adam
hiru-ai remove --group adam --yes    # deletes the folders; the references are listed for you to edit
```

## Add a gold scene (the yardstick)

See [tests/eval/adam/README.md](../../tests/eval/adam/README.md). A scene needs its script blocks, a master in the card
format written by a director, and the classic `script_split` plan as a baseline. `pytest tests/adam/test_gold.py` holds
the master to the code rules and requires it to beat the baseline.

## Add a device to the library

1. Add `sources/devices/NN-slug.md` to `adam_film_grammar` with the eight fields (copy any existing device).
2. List it under `files:` in the base's `component.yaml`.
3. Regenerate the index (below) and run `pytest tests/adam/test_knowledge.py tests/adam/test_docs.py`.
4. Ingest it (`hiru-ai ingest adam_film_grammar`). That writes to the hosted dev database: ask first.

```
.venv\Scripts\python -c "from tests.adam.test_docs import write_devices_index; write_devices_index()"
```

## Change a stage's prompt, or a gold master

The worked example in each agent's prompt, and each agent's eval cases, are GENERATED from the gold masters
(`tests/adam/stages.py`). After editing a master, a treatment draft (`tests/eval/adam/treatments/`) or the text above an
`<!-- example:start -->` marker, regenerate and run the stage tests:

```
.venv\Scripts\python -c "from tests.adam.stages import write_all; write_all()"
.venv\Scripts\python -m pytest tests/adam/test_stages.py src/libs/hiru_ai/agents/adam -q
```

`tests/adam/test_stages.py` fails when a prompt's example or a case file is out of date.

## Run an agent alone

```
.venv\Scripts\hiru-ai run agent adam_dramaturg --input case.json           # a case with an input and no reply prints exactly what would be sent
.venv\Scripts\hiru-ai eval adam_director                                   # the scripted cases (CI)
.venv\Scripts\hiru-ai eval adam_director --live                            # the real model: costs money, a person starts it
```

## The checks, run alone

```
.venv\Scripts\hiru-ai run step adam_fidelity --input src/libs/hiru_ai/steps/adam/adam_fidelity/examples/basic.json
.venv\Scripts\python -m pytest tests/adam src/libs/hiru_ai/steps/adam -q
```
