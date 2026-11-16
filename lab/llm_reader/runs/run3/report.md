# LLM reader lab · run3 · 2026-11-15 12:33

Model gpt-6.1-sol: probe (low), transcribe (low), read (medium). Code reads only the answers.

| document | verdict | expected |
|---|---|---|
| A_v1_pdf | go | go |
| B_v2_pdf | go | go |
| C_other_layout | go | go |
| D_no_lengths | needs_input | needs_input |
| E_not_a_story | stop | stop |
| F_glued_heading | stop | go |
| G_damaged_no_pdf | stop | stop |

## A_v1_pdf

_the person's v1: 'Estimated Duration: 25–30 seconds' on its own line_

**Verdict: GO** (expected go) · scored 11/11 · read from: printed pages (301 lines) · findings left: 0

| what | ok | detail |
|---|---|---|
| kind | yes | story_script |
| verdict | yes | go (expected go) |
| damaged text seen | yes | readable=False |
| episodes | yes | 3 |
| scenes | yes | 13 of 13 |
| titles | yes | all match |
| headings clean | yes | only heading words |
| lengths | yes | all match |
| leads | yes | anudi, kasun |
| crowds are groups | yes | yes |
| 'Same workspace' resolved | yes | "Kasun's small workspace" (refers back: True) |

**Gates**

- `warn` gate 0 file: the text layer is damaged; read from the printed pages

**Probe:** story_script; readable=False
- L48 `ඔයාෙ ෙෆන් එක`: Missing letters or vowel components in the possessive and phone word; Sinhala vowel signs are also placed before their consonants.
- L55 `අෙන් , Thank you! මම දැක්ෙකවත් නෑ`: Sinhala vowel signs are in the wrong character order: “අෙන්” and “දැක්ෙකවත්” should be “අනේ” and “දැක්කෙවත්”.
- L156 `ෙහාඳ අනාගතයක් ෙදන්න`: Preposed vowel signs corrupt “හොඳ” and “දෙන්න”.
- L206 `බැංකුෙවන්වත් investor ෙකෙනක්ෙගන්වත්`: Vowel signs precede the consonants they belong to, corrupting “බැංකුවෙන්වත්” and “කෙනෙක්ගෙන්වත්”.
- L249 `මෙ වාපාරය`: Letters are missing: the intended words are “මගේ ව්‍යාපාරය”.

| scene | starts (model's quote) | ends | title | place | envelope | from the words |
|---|---|---|---|---|---|---|
| E01 S01 | SCENE 01 — KASUN'S EVERYDAY LIFE (L13) | … smiles and continues working. (L26) | KASUN'S EVERYDAY LIFE | Colombo roadside – Food three-wheeler | 30 s | Estimated Duration: 25–30 seconds |
| E01 S02 | SCENE 02 — ANUDI ARRIVES (L27) | …food three-wheeler. (L37) | ANUDI ARRIVES | Colombo road – Family car and roadside | 25 s | Estimated Duration: 20–25 seconds |
| E01 S03 | SCENE 03 — THE UNEXPECTED ENCOUNTER (L38) | …es her, holding out the phone. (L50) | THE UNEXPECTED ENCOUNTER | Colombo roadside – Near Kasun's food three-wheeler | 20 s | Estimated Duration: 15–20 seconds |
| E01 S04 | SCENE 04 — A CONVERSATION THAT CHANGES EVERYTHING (L51) | …thoughts are somewhere else. (L78) | A CONVERSATION THAT CHANGES EVERYTHING | Colombo roadside – Near Kasun's food three-wheeler | 50 s | Estimated Duration: 40–50 seconds |
| E02 S01 | SCENE 01 — A FAMILIAR FACE (L83) | … gradually develops into love. (L102) | A FAMILIAR FACE | Kasun's food three-wheeler | 35 s | Estimated Duration: 30–35 seconds |
| E02 S02 | SCENE 02 — THE FATHER NOTICES (L103) | …ing, but his mind is troubled. (L113) | THE FATHER NOTICES | Colombo roadside | 25 s | Estimated Duration: 20–25 seconds |
| E02 S03 | SCENE 03 — THE CONFRONTATION (L114) | …he is protecting his daughter. (L137) | THE CONFRONTATION | Anudi's family home – Living room | 40 s | Estimated Duration: 35–40 seconds |
| E02 S04 | SCENE 04 — KASUN'S DETERMINATION AND THE BIG OPPORTUNITY (L138) | …Anudi notices his silence. (L177) | KASUN'S DETERMINATION AND THE BIG OPPORTUNITY | Kasun's small food preparation workspace | 65 s | Estimated Duration: 55–65 seconds |
| E03 S01 | SCENE 01 — THE STRUGGLE (L182) | …ause he cannot find the money. (L197) | THE STRUGGLE | Kasun's workspace and Colombo – Different locations | 35 s | Estimated Duration: 30–35 seconds |
| E03 S02 | SCENE 02 — ANUDI'S SUPPORT (L198) | …ut continues believing in him. (L213) | ANUDI'S SUPPORT | Anudi's family home – Bedroom | 25 s | Estimated Duration: 20–25 seconds |
| E03 S03 | SCENE 03 — AN UNEXPECTED OFFER (L214) | …ue and then at Anudi's father. (L237) | AN UNEXPECTED OFFER | Kasun's small workspace | 40 s | Estimated Duration: 35–40 seconds |
| E03 S04 | SCENE 04 — THE CHOICE (L238) | …tion his judgment about Kasun. (L256) | THE CHOICE | Kasun's small workspace (← Same workspace) | 35 s | Estimated Duration: 30–35 seconds |
| E03 S05 | SCENE 05 — A DREAM COMES TRUE (L257) | …ඇති." (L288) | A DREAM COMES TRUE | KASUN'S Restaurant | 55 s | Estimated Duration: 45–55 seconds |

**People:** Office workers (group); Kasun (lead); Office worker (minor); Anudi (lead); Anudi's driver (minor); Anudi's father (supporting); Customers (group); Father's driver (minor); Representative (supporting); Potential investor (minor); Friends (group); Staff members (group)

**Doubts:**
- The drivers in lines 32 and 109 may be the same person; the document does not establish this, so they are listed separately.
- Orders, thanks, conversations, and phone requests are summarized in action prose at lines 20, 34, 98, 106, 109, and 187–189; no actual spoken wording is supplied, so these are not counted as spoken dialogue lines.
- Line 187 implies a bank interlocutor but identifies no bank employee, so no separate bank character is invented.
- The late-night timing in line 190 applies to one part of episode 3 scene 1's multi-location sequence, not necessarily the whole scene.

## B_v2_pdf

_the person's v2: 'Duration: 0.46 minutes' on its own line_

**Verdict: GO** (expected go) · scored 11/11 · read from: printed pages (301 lines) · findings left: 0

| what | ok | detail |
|---|---|---|
| kind | yes | story_script |
| verdict | yes | go (expected go) |
| damaged text seen | yes | readable=False |
| episodes | yes | 3 |
| scenes | yes | 13 of 13 |
| titles | yes | all match |
| headings clean | yes | only heading words |
| lengths | yes | all match |
| leads | yes | anudi, kasun |
| crowds are groups | yes | yes |
| 'Same workspace' resolved | yes | "Kasun's small workspace" (refers back: True) |

**Gates**

- `warn` gate 0 file: the text layer is damaged; read from the printed pages

**Probe:** story_script; readable=False
- L48 `ඔයාෙ ෙෆන් එක`: Sinhala characters are missing or misordered: “ඔයාෙ” is damaged, and the word for phone has displaced or missing vowel components.
- L55 `අෙන් , Thank you! මම දැක්ෙකවත් නෑ`: Sinhala vowel signs precede the consonants they belong to: “අෙන්” and “දැක්ෙකවත්” should read “අනේ” and “දැක්කෙවත්”.
- L206 `බැංකුෙවන්වත් investor ෙකෙනක්ෙගන්වත්`: Repeated misplaced Sinhala vowel signs; these words should read “බැංකුවෙන්වත්” and “කෙනෙක්ගෙන්වත්”.
- L234 `ඔයා මෙ දුවෙගන් ඈත් ෙවන්න ඕෙන්`: “මෙ” is missing characters from “මගේ”; “දුවෙගන්”, “ෙවන්න”, and “ඕෙන්” also have displaced vowel signs.
- L249 `මෙ වාපාරය මමම ෙගාඩනගා ගන්නම්`: Letters are missing in “මෙ වාපාරය” (intended “මගේ ව්‍යාපාරය”), and the initial vowel sign in “ෙගාඩනගා” is misplaced.

| scene | starts (model's quote) | ends | title | place | envelope | from the words |
|---|---|---|---|---|---|---|
| E01 S01 | SCENE 01 — KASUN'S EVERYDAY LIFE (L13) | … smiles and continues working. (L26) | KASUN'S EVERYDAY LIFE | Colombo roadside – Food three-wheeler | 27.6 s | Duration: 0.46 minutes |
| E01 S02 | SCENE 02 — ANUDI ARRIVES (L27) | …food three-wheeler. (L37) | ANUDI ARRIVES | Colombo road – Family car and roadside | 22.8 s | Duration: 0.38 minutes |
| E01 S03 | SCENE 03 — THE UNEXPECTED ENCOUNTER (L38) | …es her, holding out the phone. (L50) | THE UNEXPECTED ENCOUNTER | Colombo roadside – Near Kasun's food three-wheeler | 17.4 s | Duration: 0.29 minutes |
| E01 S04 | SCENE 04 — A CONVERSATION THAT CHANGES EVERYTHING (L51) | …thoughts are somewhere else. (L78) | A CONVERSATION THAT CHANGES EVERYTHING | Colombo roadside – Near Kasun's food three-wheeler | 45 s | Duration: 0.75 minutes |
| E02 S01 | SCENE 01 — A FAMILIAR FACE (L83) | … gradually develops into love. (L102) | A FAMILIAR FACE | Kasun's food three-wheeler | 32.4 s | Duration: 0.54 minutes |
| E02 S02 | SCENE 02 — THE FATHER NOTICES (L103) | …ing, but his mind is troubled. (L113) | THE FATHER NOTICES | Colombo roadside | 22.8 s | Duration: 0.38 minutes |
| E02 S03 | SCENE 03 — THE CONFRONTATION (L114) | …he is protecting his daughter. (L137) | THE CONFRONTATION | Anudi's family home – Living room | 37.8 s | Duration: 0.63 minutes |
| E02 S04 | SCENE 04 — KASUN'S DETERMINATION AND THE BIG OPPORTUNITY (L138) | …Anudi notices his silence. (L177) | KASUN'S DETERMINATION AND THE BIG OPPORTUNITY | Kasun's small food preparation workspace | 60 s | Duration: 1 minute |
| E03 S01 | SCENE 01 — THE STRUGGLE (L182) | …ause he cannot find the money. (L197) | THE STRUGGLE | Kasun's workspace and Colombo – Different locations | 32.4 s | Duration: 0.54 minutes |
| E03 S02 | SCENE 02 — ANUDI'S SUPPORT (L198) | …ut continues believing in him. (L213) | ANUDI'S SUPPORT | Anudi's family home – Bedroom | 22.8 s | Duration: 0.38 minutes |
| E03 S03 | SCENE 03 — AN UNEXPECTED OFFER (L214) | …ue and then at Anudi's father. (L237) | AN UNEXPECTED OFFER | Kasun's small workspace | 37.8 s | Duration: 0.63 minutes |
| E03 S04 | SCENE 04 — THE CHOICE (L238) | …tion his judgment about Kasun. (L256) | THE CHOICE | Kasun's small workspace (← Same workspace) | 32.4 s | Duration: 0.54 minutes |
| E03 S05 | SCENE 05 — A DREAM COMES TRUE (L257) | …ඇති." (L288) | A DREAM COMES TRUE | KASUN'S Restaurant | 49.8 s | Duration: 0.83 minutes |

**People:** Kasun (lead); Anudi (lead); Anudi's father (supporting); Office workers (group); Office worker (minor); Driver (minor); Customers (group); Representative (minor); Potential investor (minor); Friends (group); Staff members (group)

**Doubts:**
- The driver in line 32 and the father's driver in line 109 may be the same person; they are provisionally grouped under Driver.
- Episode 3 scene 1 spans multiple moments; 'late at night' in line 190 applies specifically to the document-review moment, not necessarily the entire scene.
- The bank visit in line 187 implies an interlocutor, but no bank employee is explicitly identified, so no separate banker entry is added.
- Reported conversations without supplied spoken words, such as ordering tea or thanking the driver, are not included in spoken_lines.

## C_other_layout

_PART headings, '1. PLACE [approx. 28 sec]', title below, CUES, page headers_

**Verdict: GO** (expected go) · scored 11/11 · read from: text layer · findings left: 0

| what | ok | detail |
|---|---|---|
| kind | yes | story_script |
| verdict | yes | go (expected go) |
| damaged text seen | yes | readable=True |
| episodes | yes | 3 |
| scenes | yes | 13 of 13 |
| titles | yes | all match |
| headings clean | yes | only heading words |
| lengths | yes | all match |
| leads | yes | anudi, kasun |
| crowds are groups | yes | yes |
| 'Same workspace' resolved | yes | "KASUN'S SMALL WORKSPACE" (refers back: True) |

**Gates**

- none

**Probe:** story_script; readable=True

| scene | starts (model's quote) | ends | title | place | envelope | from the words |
|---|---|---|---|---|---|---|
| E01 S01 | 1. COLOMBO ROADSIDE – FOOD THREE-WHEELER  [approx. 28 sec] (L13) | … smiles and continues working. (L26) | Kasun'S Everyday Life | COLOMBO ROADSIDE – FOOD THREE-WHEELER | 28 s | [approx. 28 sec] |
| E01 S02 | 2. COLOMBO ROAD – FAMILY CAR AND ROADSIDE  [approx. 23 sec] (L27) | …food three-wheeler. (L36) | Anudi Arrives | COLOMBO ROAD – FAMILY CAR AND ROADSIDE | 23 s | [approx. 23 sec] |
| E01 S03 | 3. COLOMBO ROADSIDE – NEAR KASUN'S FOOD THREE-WHEELER  [approx. 17 sec] (L37) | …es her, holding out the phone. (L50) | The Unexpected Encounter | COLOMBO ROADSIDE – NEAR KASUN'S FOOD THREE-WHEELER | 17 s | [approx. 17 sec] |
| E01 S04 | 4. COLOMBO ROADSIDE – NEAR KASUN'S FOOD THREE-WHEELER  [approx. 45 sec] (L51) | …thoughts are somewhere else. (L88) | A Conversation That Changes Everything | COLOMBO ROADSIDE – NEAR KASUN'S FOOD THREE-WHEELER | 45 s | [approx. 45 sec] |
| E02 S01 | 1. KASUN'S FOOD THREE-WHEELER – DIFFERENT EVENINGS  [approx. 32 sec] (L94) | … gradually develops into love. (L114) | A Familiar Face | KASUN'S FOOD THREE-WHEELER | 32 s | [approx. 32 sec] |
| E02 S02 | 2. COLOMBO ROADSIDE – EVENING  [approx. 23 sec] (L115) | …ing, but his mind is troubled. (L124) | The Father Notices | COLOMBO ROADSIDE | 23 s | [approx. 23 sec] |
| E02 S03 | 3. ANUDI'S FAMILY HOME – LIVING ROOM  [approx. 38 sec] (L125) | …he is protecting his daughter. (L155) | The Confrontation | ANUDI'S FAMILY HOME – LIVING ROOM | 38 s | [approx. 38 sec] |
| E02 S04 | 4. KASUN'S SMALL FOOD PREPARATION WORKSPACE  [approx. 60 sec] (L156) | …Anudi notices his silence. (L204) | Kasun'S Determination And The Big Opportunity | KASUN'S SMALL FOOD PREPARATION WORKSPACE | 60 s | [approx. 60 sec] |
| E03 S01 | 1. KASUN'S WORKSPACE AND COLOMBO – DIFFERENT LOCATIONS  [approx. 32 sec] (L209) | …ause he cannot find the money. (L223) | The Struggle | KASUN'S WORKSPACE AND COLOMBO – DIFFERENT LOCATIONS | 32 s | [approx. 32 sec] |
| E03 S02 | 2. ANUDI'S FAMILY HOME – BEDROOM  [approx. 23 sec] (L224) | …ut continues believing in him. (L243) | Anudi'S Support | ANUDI'S FAMILY HOME – BEDROOM | 23 s | [approx. 23 sec] |
| E03 S03 | 3. KASUN'S SMALL WORKSPACE  [approx. 38 sec] (L244) | …ue and then at Anudi's father. (L272) | An Unexpected Offer | KASUN'S SMALL WORKSPACE | 38 s | [approx. 38 sec] |
| E03 S04 | 4. SAME WORKSPACE  [approx. 32 sec] (L273) | …tion his judgment about Kasun. (L293) | The Choice | KASUN'S SMALL WORKSPACE (← SAME WORKSPACE) | 32 s | [approx. 32 sec] |
| E03 S05 | 5. KASUN'S RESTAURANT – DAY  [approx. 50 sec] (L294) | …ඇති." (L329) | A Dream Comes True | KASUN'S RESTAURANT | 50 s | [approx. 50 sec] |

**People:** Kasun (lead); Street commuters (group); Office worker (minor); Anudi (lead); Driver (minor); Anudi's father (supporting); Customers (group); Representative (supporting); Potential investor (minor); Friends (group); Staff members (group)

**Doubts:**
- The document declares “Episodes: 3” at line 6 but labels its divisions PART ONE, PART TWO and PART THREE (lines 11, 90 and 206); these are treated as the three episodes.
- Spoken-action summaries are included in spoken_lines where speech is explicit, even though exact dialogue is not supplied: thanks at line 33, talking/goodbyes at lines 110 and 113, conversation/request at lines 117 and 120, and discussions/calls at lines 213–215. The tea order at line 19 may be spoken or gestural, so it is not counted as definite spoken dialogue.
- The driver in line 31 and “the driver” in line 120 are recorded as one unnamed person, but their identity is not explicitly confirmed; line 124 also says the father “continues driving” despite the driver reference.
- Line 213 says Kasun “discusses a business loan” at a bank, but no bank employee is individually identified; no separate bank employee has been invented.
- Friends are contacted at line 215 and unable to help at line 220, but the document supplies no individual identities or explicit spoken replies.
- The “late at night” wording in line 216 applies to one moment within the multi-location struggle montage, not necessarily the whole scene.

## D_no_lengths

_no lengths except E02 S02 in a sentence: 'about half a minute'_

**Verdict: NEEDS_INPUT** (expected needs_input) · scored 11/11 · read from: text layer · findings left: 0

| what | ok | detail |
|---|---|---|
| kind | yes | story_script |
| verdict | yes | needs_input (expected needs_input) |
| damaged text seen | yes | readable=True |
| episodes | yes | 3 |
| scenes | yes | 13 of 13 |
| titles | yes | all match |
| headings clean | yes | only heading words |
| lengths | yes | all match |
| leads | yes | anudi, kasun |
| crowds are groups | yes | yes |
| 'Same workspace' resolved | yes | "Kasun's small workspace" (refers back: True) |

**Gates**

- `needs_input` gate 4 scene: 12 of 13 scenes states no length: E01 S01, E01 S02, E01 S03, E01 S04, E02 S01, E02 S03, E02 S04, E03 S01, E03 S02, E03 S03, E03 S04, E03 S05

**Probe:** story_script; readable=True

| scene | starts (model's quote) | ends | title | place | envelope | from the words |
|---|---|---|---|---|---|---|
| E01 S01 | SCENE 01 — KASUN'S EVERYDAY LIFE (L13) | … smiles and continues working. (L25) | KASUN'S EVERYDAY LIFE | Colombo roadside – Food three-wheeler | — | — |
| E01 S02 | SCENE 02 — ANUDI ARRIVES (L26) | …food three-wheeler. (L35) | ANUDI ARRIVES | Colombo road – Family car and roadside | — | — |
| E01 S03 | SCENE 03 — THE UNEXPECTED ENCOUNTER (L36) | …es her, holding out the phone. (L47) | THE UNEXPECTED ENCOUNTER | Colombo roadside – Near Kasun's food three-wheeler | — | — |
| E01 S04 | SCENE 04 — A CONVERSATION THAT CHANGES EVERYTHING (L48) | …thoughts are somewhere else. (L74) | A CONVERSATION THAT CHANGES EVERYTHING | Colombo roadside – Near Kasun's food three-wheeler | — | — |
| E02 S01 | SCENE 01 — A FAMILIAR FACE (L79) | … gradually develops into love. (L97) | A FAMILIAR FACE | Kasun's food three-wheeler | — | — |
| E02 S02 | SCENE 02 — THE FATHER NOTICES (L98) | …ing, but his mind is troubled. (L108) | THE FATHER NOTICES | Colombo roadside | 30 s | This short moment should play for about half a minute on screen. |
| E02 S03 | SCENE 03 — THE CONFRONTATION (L109) | …he is protecting his daughter. (L131) | THE CONFRONTATION | Anudi's family home – Living room | — | — |
| E02 S04 | SCENE 04 — KASUN'S DETERMINATION AND THE BIG OPPORTUNITY (L132) | …Anudi notices his silence. (L170) | KASUN'S DETERMINATION AND THE BIG OPPORTUNITY | Kasun's small food preparation workspace | — | — |
| E03 S01 | SCENE 01 — THE STRUGGLE (L175) | …ause he cannot find the money. (L189) | THE STRUGGLE | Kasun's workspace and Colombo – Different locations | — | — |
| E03 S02 | SCENE 02 — ANUDI'S SUPPORT (L190) | …ut continues believing in him. (L204) | ANUDI'S SUPPORT | Anudi's family home – Bedroom | — | — |
| E03 S03 | SCENE 03 — AN UNEXPECTED OFFER (L205) | …ue and then at Anudi's father. (L227) | AN UNEXPECTED OFFER | Kasun's small workspace | — | — |
| E03 S04 | SCENE 04 — THE CHOICE (L228) | …tion his judgment about Kasun. (L245) | THE CHOICE | Kasun's small workspace (← Same workspace) | — | — |
| E03 S05 | SCENE 05 — A DREAM COMES TRUE (L246) | …ඇති." (L276) | A DREAM COMES TRUE | KASUN'S Restaurant | — | — |

**People:** Kasun (lead); Office workers (group); Office worker (minor); Anudi (lead); Anudi's driver (minor); Anudi's father (supporting); Customers (group); Father's driver (minor); Representative (supporting); Potential investor (minor); Friends (group); Staff members (group)

**Doubts:**
- The drivers at lines 30 and 104 may be the same family employee; the document does not establish this, so they are listed separately.
- Reported conversations without supplied spoken wording, such as ordering tea, thanking the driver and asking the driver to slow down, are not counted as spoken_lines.
- Episode 3 scene 1 includes 'late at night' at line 182 for one moment in its multi-location sequence, not necessarily the whole scene.
- The bank discussion at line 179 implies a counterpart, but no bank employee is individually identified or explicitly described as appearing; no separate person has been invented.
- Line 100 is an embedded production instruction, retained as the scene's stated approximate duration and also marked as non-story.

## E_not_a_story

_title page + cast list + budget: no story_

**Verdict: STOP** (expected stop) · scored 3/3 · read from: — · findings left: 0

| what | ok | detail |
|---|---|---|
| kind | yes | other_not_story |
| verdict | yes | stop (expected stop) |
| damaged text seen | yes | readable=True |

**Gates**

- `stop` gate 1 kind: not a story to build from: other_not_story (Production notes and budget headed “CAST & CREW NOTES” and “BUDGET (draft)”; no enacted or narrated story.)

**Probe:** other_not_story; readable=True

## F_glued_heading

_v2 with two SCENE 04 headings glued to the line before_

**Verdict: STOP** (expected go) · scored 1/3 · read from: — · findings left: 0

| what | ok | detail |
|---|---|---|
| kind | yes | story_script |
| verdict | **NO** | stop (expected go) |
| damaged text seen | **NO** | readable=False |

**Gates**

- `stop` gate 0 file: the text is damaged and there is no PDF to read the printed pages from

**Probe:** story_script; readable=False
- L137 `Her father remains seated, convinced that he is protecting his daughter.SCENE 04 — KASUN'S DETERMINATION AND THE BIG OPPORTUNITY`: The next scene heading is glued to the preceding action sentence; a separating line break is missing.
- L236 `He looks at the cheque and then at Anudi's father.SCENE 04 — THE CHOICE`: The next scene heading is glued to the preceding action sentence; a separating line break is missing.

## G_damaged_no_pdf

_v2's damaged text with no PDF behind it_

**Verdict: STOP** (expected stop) · scored 3/3 · read from: — · findings left: 0

| what | ok | detail |
|---|---|---|
| kind | yes | story_script |
| verdict | yes | stop (expected stop) |
| damaged text seen | yes | readable=False |

**Gates**

- `stop` gate 0 file: the text is damaged and there is no PDF to read the printed pages from

**Probe:** story_script; readable=False
- L48 `ඔයාෙ ෙෆන් එක`: Sinhala characters are missing in the possessive and the word for phone; a vowel sign is also placed before its consonant.
- L56 `ෙවන්න`: The vowel sign precedes its consonant; correct character order is “වෙන්න”.
- L206 `ෙකෙනක්ෙගන්වත්`: Multiple Sinhala vowel signs precede their consonants; this should be “කෙනෙක්ගෙන්වත්”.
- L232 `ෙකාන්ෙසියක්`: The word has misplaced vowel signs and missing consonants; the intended word is “කොන්දේසියක්”.
- L249 `මෙ වාපාරය`: Letters are missing: the possessive “මගේ” and the consonant cluster in “ව්‍යාපාරය” are damaged.

Lab spent $0.8662 of $2.00.
