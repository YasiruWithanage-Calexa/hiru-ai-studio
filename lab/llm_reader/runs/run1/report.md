# LLM reader lab · run1 · 2026-11-15 11:25

Model gpt-6.1-sol (medium). One reading call per document, at most one repair. Code reads only the answer.

| document | verdict | expected | scored | findings left |
|---|---|---|---|---|
| A_v1_pdf | go | go | 9/9 | 0 |
| B_v2_pdf | go | go | 9/9 | 0 |
| C_other_layout | go | go | 9/9 | 0 |
| D_no_lengths | needs_input | needs_input | 9/9 | 0 |
| E_not_a_story | stop | stop | 2/2 | 0 |
| F_glued_heading | go | go | 9/9 | 0 |

## A_v1_pdf

_the person's v1: 'Estimated Duration: 25–30 seconds' on its own line_

**Verdict: GO** (expected go) · scored 9/9 · check findings left: 0

| what | ok | detail |
|---|---|---|
| kind | yes | story_script |
| verdict | yes | go (expected go) |
| episodes | yes | 3 |
| scenes | yes | 13 of 13 |
| titles | yes | all match |
| headings clean | yes | only heading words |
| lengths | yes | all match |
| main people | yes | anudi, anudi's father, kasun |
| damaged text seen | yes | readable=False, 5 examples |

**Gates**

- `warn` gate 0 file: the text layer is damaged (line 25: Sinhala vowel signs appear before their consonants; copying the dialogue would preserve damaged character order.; line 48: The dialogue contains missing Sinhala letters or signs as well as displaced vowel signs.); read it from page images instead

| scene | heading (model's quote) | title | place | length | from the words |
|---|---|---|---|---|---|
| E01 S01 | SCENE 01 — KASUN'S EVERYDAY LIFE (L13) | KASUN'S EVERYDAY LIFE | Colombo roadside – Food three-wheeler | 25–30 s | Estimated Duration: 25–30 seconds |
| E01 S02 | SCENE 02 — ANUDI ARRIVES (L27) | ANUDI ARRIVES | Colombo road – Family car and roadside | 20–25 s | Estimated Duration: 20–25 seconds |
| E01 S03 | SCENE 03 — THE UNEXPECTED ENCOUNTER (L38) | THE UNEXPECTED ENCOUNTER | Colombo roadside – Near Kasun's food three-wheeler | 15–20 s | Estimated Duration: 15–20 seconds |
| E01 S04 | SCENE 04 — A CONVERSATION THAT CHANGES EVERYTHING (L51) | A CONVERSATION THAT CHANGES EVERYTHING | Colombo roadside – Near Kasun's food three-wheeler | 40–50 s | Estimated Duration: 40–50 seconds |
| E02 S01 | SCENE 01 — A FAMILIAR FACE (L83) | A FAMILIAR FACE | Kasun's food three-wheeler | 30–35 s | Estimated Duration: 30–35 seconds |
| E02 S02 | SCENE 02 — THE FATHER NOTICES (L103) | THE FATHER NOTICES | Colombo roadside | 20–25 s | Estimated Duration: 20–25 seconds |
| E02 S03 | SCENE 03 — THE CONFRONTATION (L114) | THE CONFRONTATION | Anudi's family home – Living room | 35–40 s | Estimated Duration: 35–40 seconds |
| E02 S04 | SCENE 04 — KASUN'S DETERMINATION AND THE BIG OPPORTUNITY (L138) | KASUN'S DETERMINATION AND THE BIG OPPORTUNITY | Kasun's small food preparation workspace | 55–65 s | Estimated Duration: 55–65 seconds |
| E03 S01 | SCENE 01 — THE STRUGGLE (L182) | THE STRUGGLE | Kasun's workspace and Colombo – Different locations | 30–35 s | Estimated Duration: 30–35 seconds |
| E03 S02 | SCENE 02 — ANUDI'S SUPPORT (L198) | ANUDI'S SUPPORT | Anudi's family home – Bedroom | 20–25 s | Estimated Duration: 20–25 seconds |
| E03 S03 | SCENE 03 — AN UNEXPECTED OFFER (L214) | AN UNEXPECTED OFFER | Kasun's small workspace | 35–40 s | Estimated Duration: 35–40 seconds |
| E03 S04 | SCENE 04 — THE CHOICE (L238) | THE CHOICE | Same workspace | 30–35 s | Estimated Duration: 30–35 seconds |
| E03 S05 | SCENE 05 — A DREAM COMES TRUE (L257) | A DREAM COMES TRUE | KASUN'S Restaurant | 45–55 s | Estimated Duration: 45–55 seconds |

**People:** Kasun (main) aka කසුන්; Anudi (main) aka අනුදි; Anudi's father (main) aka Father, Father (over the phone), Her father, The father; Office workers; Office worker aka customer; Anudi's driver; Food-business customers; Father's driver; Representative aka Representative (over the phone); Potential investor aka investor; Kasun's friends aka friends; Restaurant staff aka Staff members; Restaurant customers

**Kind:** story_script (A scene-by-scene drama script with action, character-labelled dialogue, locations and estimated durations, introduced as “Revised Cinematic Story & Scene Breakdown” on line 2.)

**Text quality:** readable=False
- L25 `ෙරස්ටුරන්ට්`: Sinhala vowel signs appear before their consonants; copying the dialogue would preserve damaged character order.
- L48 `ඔයාෙ ෙෆන්`: The dialogue contains missing Sinhala letters or signs as well as displaced vowel signs.
- L60 `හැමෙම`: The Sinhala word is damaged, with letters or signs missing.
- L167 `වුෙ`: The Sinhala word has missing letters or signs.
- L249 `මෙ වාපාරය`: Missing Sinhala letters or signs damage both words.

**Skipped:** L1-10 title_page; L12-12 production_notes; L79-79 end_marker; L81-82 production_notes; L178-178 end_marker; L180-181 production_notes; L289-289 end_marker; L290-301 production_notes

**Doubts:**
- The drivers on lines 32 and 109 may be the same family employee, but the document does not establish this; they are listed separately.
- Unnamed background groups are recorded collectively because the document does not identify or count their members.
- Line 187 says “He visits a bank and discusses a business loan.” No bank employee is explicitly identified, so no separate bank character is asserted.
- Narrated speech acts, such as ordering tea on line 20, thanking the driver on line 34 and asking the driver to slow down on line 109, provide no actual spoken wording; they are not included in spoken_lines.
- Episode 3 scene 1 spans multiple moments; “late at night” on line 190 applies to the document-review portion, not necessarily the entire scene.
- The final text on lines 286–288 is explicitly on-screen text, not dialogue, and remains part of the final scene.
- Sinhala text corruption prevents confidently recovering the intended wording of several spoken lines; quotations preserve the supplied text without correction.

## B_v2_pdf

_the person's v2: 'Duration: 0.46 minutes' on its own line_

**Verdict: GO** (expected go) · scored 9/9 · check findings left: 0

| what | ok | detail |
|---|---|---|
| kind | yes | story_script |
| verdict | yes | go (expected go) |
| episodes | yes | 3 |
| scenes | yes | 13 of 13 |
| titles | yes | all match |
| headings clean | yes | only heading words |
| lengths | yes | all match |
| main people | yes | anudi, anudi's father, kasun |
| damaged text seen | yes | readable=False, 5 examples |

**Gates**

- `warn` gate 0 file: the text layer is damaged (line 25: Sinhala vowel signs appear before their consonants, damaging the copied dialogue.; line 48: The possessive and the word for phone have missing or displaced Sinhala characters.); read it from page images instead

| scene | heading (model's quote) | title | place | length | from the words |
|---|---|---|---|---|---|
| E01 S01 | SCENE 01 — KASUN'S EVERYDAY LIFE (L13) | KASUN'S EVERYDAY LIFE | Colombo roadside – Food three-wheeler | 27.6–27.6 s | Duration: 0.46 minutes |
| E01 S02 | SCENE 02 — ANUDI ARRIVES (L27) | ANUDI ARRIVES | Colombo road – Family car and roadside | 22.8–22.8 s | Duration: 0.38 minutes |
| E01 S03 | SCENE 03 — THE UNEXPECTED ENCOUNTER (L38) | THE UNEXPECTED ENCOUNTER | Colombo roadside – Near Kasun's food three-wheeler | 17.4–17.4 s | Duration: 0.29 minutes |
| E01 S04 | SCENE 04 — A CONVERSATION THAT CHANGES EVERYTHING (L51) | A CONVERSATION THAT CHANGES EVERYTHING | Colombo roadside – Near Kasun's food three-wheeler | 45–45 s | Duration: 0.75 minutes |
| E02 S01 | SCENE 01 — A FAMILIAR FACE (L83) | A FAMILIAR FACE | Kasun's food three-wheeler | 32.4–32.4 s | Duration: 0.54 minutes |
| E02 S02 | SCENE 02 — THE FATHER NOTICES (L103) | THE FATHER NOTICES | Colombo roadside | 22.8–22.8 s | Duration: 0.38 minutes |
| E02 S03 | SCENE 03 — THE CONFRONTATION (L114) | THE CONFRONTATION | Anudi's family home – Living room | 37.8–37.8 s | Duration: 0.63 minutes |
| E02 S04 | SCENE 04 — KASUN'S DETERMINATION AND THE BIG OPPORTUNITY (L138) | KASUN'S DETERMINATION AND THE BIG OPPORTUNITY | Kasun's small food preparation workspace | 60–60 s | Duration: 1 minute |
| E03 S01 | SCENE 01 — THE STRUGGLE (L182) | THE STRUGGLE | Kasun's workspace and Colombo – Different locations | 32.4–32.4 s | Duration: 0.54 minutes |
| E03 S02 | SCENE 02 — ANUDI'S SUPPORT (L198) | ANUDI'S SUPPORT | Anudi's family home – Bedroom | 22.8–22.8 s | Duration: 0.38 minutes |
| E03 S03 | SCENE 03 — AN UNEXPECTED OFFER (L214) | AN UNEXPECTED OFFER | Kasun's small workspace | 37.8–37.8 s | Duration: 0.63 minutes |
| E03 S04 | SCENE 04 — THE CHOICE (L238) | THE CHOICE | Same workspace | 32.4–32.4 s | Duration: 0.54 minutes |
| E03 S05 | SCENE 05 — A DREAM COMES TRUE (L257) | A DREAM COMES TRUE | KASUN'S Restaurant | 49.8–49.8 s | Duration: 0.83 minutes |

**People:** Kasun (main) aka කසුන්; Anudi (main) aka අනුදි; Anudi's father (main) aka Father, Father (over the phone), Her father, The father; Office worker aka customer; Anudi's driver; Father's driver; Representative aka Representative (over the phone), A representative from a major supermarket chain; Potential investor aka The investor; Kasun's friends aka His friends; Background office workers; Customers; Restaurant staff aka Staff members

**Kind:** story_script (A scene-by-scene dramatic script combining action descriptions and attributed dialogue; identified on line 2 as "Revised Cinematic Story & Scene Breakdown".)

**Text quality:** readable=False
- L25 `ෙරස්ටුරන්ට්`: Sinhala vowel signs appear before their consonants, damaging the copied dialogue.
- L48 `ඔයාෙ ෙෆන්`: The possessive and the word for phone have missing or displaced Sinhala characters.
- L55 `අෙන්`: The Sinhala vowel sign is displaced before its consonant.
- L60 `හැමෙම`: The dialogue contains a damaged word with missing or incorrect Sinhala characters.
- L206 `ෙකෙනක්ෙගන්වත්`: Multiple Sinhala vowel signs are displaced before the consonants to which they belong.

**Skipped:** L1-10 title_page; L12-12 other; L79-79 end_marker; L81-82 other; L178-178 end_marker; L180-181 other; L289-289 end_marker; L290-301 production_notes

**Doubts:**
- The drivers on lines 32 ("The driver stops near an office building.") and 109 ("He asks the driver to slow down.") may be the same person; the document does not establish this, so they are listed as separate roles.
- Some speech is summarized without giving its words, such as line 20 ("An office worker approaches and orders tea."), line 34 ("She thanks the driver and walks toward the building.") and line 109 ("He asks the driver to slow down."); spoken_lines records actual supplied dialogue, not these summaries.
- Episode 3, scene 1 spans several moments; "late at night" on line 190 applies specifically to reviewing documents, not necessarily to the whole scene.
- The unnamed customers, friends, staff and background office workers are collective entries because the document does not distinguish individuals.
- The final message is explicitly introduced by line 286, "FINAL TEXT ON SCREEN:", so lines 287–288 remain story content but are not counted as speech.

## C_other_layout

_PART headings, '1. PLACE [approx. 28 sec]', title below, CUES, page headers_

**Verdict: GO** (expected go) · scored 9/9 · check findings left: 0

| what | ok | detail |
|---|---|---|
| kind | yes | story_script |
| verdict | yes | go (expected go) |
| episodes | yes | 3 |
| scenes | yes | 13 of 13 |
| titles | yes | all match |
| headings clean | yes | only heading words |
| lengths | yes | all match |
| main people | yes | anudi, anudi's father, kasun |
| damaged text seen | yes | readable=False, 5 examples |

**Gates**

- `warn` gate 0 file: the text layer is damaged (line 25: A Sinhala vowel sign precedes its consonant instead of being correctly ordered.; line 48: The possessive word appears to have a missing consonant, and the following word has damaged vowel ordering or missing signs.); read it from page images instead

| scene | heading (model's quote) | title | place | length | from the words |
|---|---|---|---|---|---|
| E01 S01 | 1. COLOMBO ROADSIDE – FOOD THREE-WHEELER  [approx. 28 sec] (L13) | Kasun'S Everyday Life | COLOMBO ROADSIDE – FOOD THREE-WHEELER | 28–28 s | [approx. 28 sec] |
| E01 S02 | 2. COLOMBO ROAD – FAMILY CAR AND ROADSIDE  [approx. 23 sec] (L27) | Anudi Arrives | COLOMBO ROAD – FAMILY CAR AND ROADSIDE | 23–23 s | [approx. 23 sec] |
| E01 S03 | 3. COLOMBO ROADSIDE – NEAR KASUN'S FOOD THREE-WHEELER  [approx. 17 sec] (L37) | The Unexpected Encounter | COLOMBO ROADSIDE – NEAR KASUN'S FOOD THREE-WHEELER | 17–17 s | [approx. 17 sec] |
| E01 S04 | 4. COLOMBO ROADSIDE – NEAR KASUN'S FOOD THREE-WHEELER  [approx. 45 sec] (L51) | A Conversation That Changes Everything | COLOMBO ROADSIDE – NEAR KASUN'S FOOD THREE-WHEELER | 45–45 s | [approx. 45 sec] |
| E02 S01 | 1. KASUN'S FOOD THREE-WHEELER – DIFFERENT EVENINGS  [approx. 32 sec] (L94) | A Familiar Face | KASUN'S FOOD THREE-WHEELER | 32–32 s | [approx. 32 sec] |
| E02 S02 | 2. COLOMBO ROADSIDE – EVENING  [approx. 23 sec] (L115) | The Father Notices | COLOMBO ROADSIDE | 23–23 s | [approx. 23 sec] |
| E02 S03 | 3. ANUDI'S FAMILY HOME – LIVING ROOM  [approx. 38 sec] (L125) | The Confrontation | ANUDI'S FAMILY HOME – LIVING ROOM | 38–38 s | [approx. 38 sec] |
| E02 S04 | 4. KASUN'S SMALL FOOD PREPARATION WORKSPACE  [approx. 60 sec] (L156) | Kasun'S Determination And The Big Opportunity | KASUN'S SMALL FOOD PREPARATION WORKSPACE | 60–60 s | [approx. 60 sec] |
| E03 S01 | 1. KASUN'S WORKSPACE AND COLOMBO – DIFFERENT LOCATIONS  [approx. 32 sec] (L209) | The Struggle | KASUN'S WORKSPACE AND COLOMBO – DIFFERENT LOCATIONS | 32–32 s | [approx. 32 sec] |
| E03 S02 | 2. ANUDI'S FAMILY HOME – BEDROOM  [approx. 23 sec] (L224) | Anudi'S Support | ANUDI'S FAMILY HOME – BEDROOM | 23–23 s | [approx. 23 sec] |
| E03 S03 | 3. KASUN'S SMALL WORKSPACE  [approx. 38 sec] (L244) | An Unexpected Offer | KASUN'S SMALL WORKSPACE | 38–38 s | [approx. 38 sec] |
| E03 S04 | 4. SAME WORKSPACE  [approx. 32 sec] (L273) | The Choice | SAME WORKSPACE | 32–32 s | [approx. 32 sec] |
| E03 S05 | 5. KASUN'S RESTAURANT – DAY  [approx. 50 sec] (L294) | A Dream Comes True | KASUN'S RESTAURANT | 50–50 s | [approx. 50 sec] |

**People:** Kasun (main) aka KASUN; Office worker aka customer; Office workers; Anudi (main) aka ANUDI; Anudi's driver aka driver; Anudi's father (main) aka FATHER, FATHER (V.O.), Her father, The father; Food-business customers aka customers; Father's driver; Supermarket representative aka REPRESENTATIVE (V.O.); Potential investor aka investor; Kasun's friends aka friends; Restaurant staff aka Staff members; Restaurant customers

**Kind:** story_script (A dramatic script with numbered scenes, action descriptions, character cues and dialogue, organized into three parts.)

**Text quality:** readable=False
- L25 `ෙරස්ටුරන්ට්`: A Sinhala vowel sign precedes its consonant instead of being correctly ordered.
- L48 `ඔයාෙ ෙෆන්`: The possessive word appears to have a missing consonant, and the following word has damaged vowel ordering or missing signs.
- L66 `රැපියල්`: The vowel sign in the word for rupees is incorrect.
- L185 `ඔයාලෙ food products අෙ branches කිහිපයකට`: Sinhala words appear to have missing consonants or vowel components; copying this dialogue would preserve the damage.
- L285 `මෙ වාපාරය`: The possessive and the word for business appear to be missing letters or combining components.

**Skipped:** L1-6 title_page; L7-10 production_notes; L12-12 production_notes; L46-46 page_furniture; L89-89 end_marker; L91-91 page_furniture; L92-93 production_notes; L136-136 page_furniture; L182-182 page_furniture; L205-205 end_marker; L207-208 production_notes; L227-227 page_furniture; L271-271 page_furniture; L317-317 page_furniture; L330-330 end_marker; L331-342 production_notes

**Doubts:**
- The document declares three episodes at line 6 but labels its three divisions PART ONE, PART TWO and PART THREE; these are treated as the three episodes.
- The driver at line 31 and the father's driver at line 120 may be the same person, but the document does not establish this; they are listed separately.
- Lines 19, 33, 120 and 213–215 summarize orders, thanks or conversations without supplying spoken wording; they are not counted as dialogue lines.
- The friends in lines 215–220 are telephone contacts whose individual appearances or audible responses are not specified.
- The bank visit in line 213 implies an interlocutor but identifies no bank employee, so no separate bank character has been invented.
- The late-night reference at line 216 applies to one moment within the multi-location struggle montage, not necessarily the entire scene.
- Unnamed background groups are listed collectively; the document does not identify their individual members or establish overlap between roadside and restaurant customers.

## D_no_lengths

_no lengths except E02 S02 in a sentence: 'about half a minute'_

**Verdict: NEEDS_INPUT** (expected needs_input) · scored 9/9 · check findings left: 0

| what | ok | detail |
|---|---|---|
| kind | yes | story_script |
| verdict | yes | needs_input (expected needs_input) |
| episodes | yes | 3 |
| scenes | yes | 13 of 13 |
| titles | yes | all match |
| headings clean | yes | only heading words |
| lengths | yes | all match |
| main people | yes | anudi, anudi's father, kasun |
| damaged text seen | yes | readable=False, 5 examples |

**Gates**

- `warn` gate 0 file: the text layer is damaged (line 24: A Sinhala vowel sign precedes its consonant; copying this dialogue would preserve damaged character order.; line 45: The Sinhala words have missing letters or vowel components and misplaced vowel signs.); read it from page images instead
- `needs_input` gate 2 structure: 12 of 13 scenes state no length: E01 S01, E01 S02, E01 S03, E01 S04, E02 S01, E02 S03, E02 S04, E03 S01, E03 S02, E03 S03, E03 S04, E03 S05

| scene | heading (model's quote) | title | place | length | from the words |
|---|---|---|---|---|---|
| E01 S01 | SCENE 01 — KASUN'S EVERYDAY LIFE (L13) | KASUN'S EVERYDAY LIFE | Colombo roadside – Food three-wheeler | — | — |
| E01 S02 | SCENE 02 — ANUDI ARRIVES (L26) | ANUDI ARRIVES | Colombo road – Family car and roadside | — | — |
| E01 S03 | SCENE 03 — THE UNEXPECTED ENCOUNTER (L36) | THE UNEXPECTED ENCOUNTER | Colombo roadside – Near Kasun's food three-wheeler | — | — |
| E01 S04 | SCENE 04 — A CONVERSATION THAT CHANGES EVERYTHING (L48) | A CONVERSATION THAT CHANGES EVERYTHING | Colombo roadside – Near Kasun's food three-wheeler | — | — |
| E02 S01 | SCENE 01 — A FAMILIAR FACE (L79) | A FAMILIAR FACE | Kasun's food three-wheeler | — | — |
| E02 S02 | SCENE 02 — THE FATHER NOTICES (L98) | THE FATHER NOTICES | Colombo roadside | 30–30 s | This short moment should play for about half a minute on screen. |
| E02 S03 | SCENE 03 — THE CONFRONTATION (L109) | THE CONFRONTATION | Anudi's family home – Living room | — | — |
| E02 S04 | SCENE 04 — KASUN'S DETERMINATION AND THE BIG OPPORTUNITY (L132) | KASUN'S DETERMINATION AND THE BIG OPPORTUNITY | Kasun's small food preparation workspace | — | — |
| E03 S01 | SCENE 01 — THE STRUGGLE (L175) | THE STRUGGLE | Kasun's workspace and Colombo – Different locations | — | — |
| E03 S02 | SCENE 02 — ANUDI'S SUPPORT (L190) | ANUDI'S SUPPORT | Anudi's family home – Bedroom | — | — |
| E03 S03 | SCENE 03 — AN UNEXPECTED OFFER (L205) | AN UNEXPECTED OFFER | Kasun's small workspace | — | — |
| E03 S04 | SCENE 04 — THE CHOICE (L228) | THE CHOICE | Same workspace | — | — |
| E03 S05 | SCENE 05 — A DREAM COMES TRUE (L246) | A DREAM COMES TRUE | KASUN'S Restaurant | — | — |

**People:** Kasun (main); Anudi (main); Anudi's father (main) aka Father, Father (over the phone), The father, Her father; Office worker aka customer; Office workers; Anudi's driver; Father's driver; Representative aka Representative (over the phone); Potential investor aka investor; Kasun's friends aka friends; Customers; Staff members

**Kind:** story_script (A three-episode drama presented as numbered scenes with locations, action and character-labelled dialogue.)

**Text quality:** readable=False
- L24 `ෙරස්ටුරන්ට්`: A Sinhala vowel sign precedes its consonant; copying this dialogue would preserve damaged character order.
- L45 `ඔයාෙ ෙෆන්`: The Sinhala words have missing letters or vowel components and misplaced vowel signs.
- L51 `අෙන්`: The vowel sign is displaced before the consonant it belongs to.
- L120 `මෙ යාළුෙවක්`: The possessive word is missing a letter, and the following word has a misplaced vowel sign.
- L268 `ෙකෙනක්`: Sinhala vowel signs are placed before their consonants.

**Skipped:** L1-10 title_page; L12-12 production_notes; L75-75 end_marker; L77-78 production_notes; L171-171 end_marker; L173-174 production_notes; L277-277 end_marker; L278-289 production_notes

**Doubts:**
- The drivers at lines 30 and 104 may be the same family employee; the document does not establish this, so they are listed separately.
- Unnamed plural participants are retained as groups because the document does not distinguish individuals.
- Line 179 says Kasun discusses a bank loan but identifies no bank employee; no separate bank employee has been invented.
- Speakers include people explicitly described as ordering, thanking, talking or making requests in narrative; spoken_lines lists only actual supplied dialogue, not narrative summaries of speech.
- Episode 3 scene 1 spans multiple moments; 'late at night' at line 182 applies to one portion, not necessarily the whole scene.
- The duration at line 100 is approximate: 'about half a minute' is recorded as 30 seconds.
- The Sinhala dialogue is substantially damaged; original spellings are preserved in quotations rather than silently repaired.

## E_not_a_story

_title page + cast list + budget: no story_

**Verdict: STOP** (expected stop) · scored 2/2 · check findings left: 0

| what | ok | detail |
|---|---|---|
| kind | yes | other_not_story |
| verdict | yes | stop (expected stop) |

**Gates**

- `warn` gate 0 file: the text layer is damaged (line 1: The Sinhala vowel sign precedes its consonant; the expected spelling is දෙන්නා.); read it from page images instead
- `stop` gate 1 kind: not a story to build from: other_not_story (The document contains project metadata, cast and crew notes, and a draft budget, but no story action or dialogue. Its sections include “CAST & CREW NOTES” (line 11) and “BUDGET (draft)” (line 16).)

**People:** 

**Kind:** other_not_story (The document contains project metadata, cast and crew notes, and a draft budget, but no story action or dialogue. Its sections include “CAST & CREW NOTES” (line 11) and “BUDGET (draft)” (line 16).)

**Text quality:** readable=False
- L1 `ෙදන්නා`: The Sinhala vowel sign precedes its consonant; the expected spelling is දෙන්නා.

**Skipped:** L1-6 title_page; L7-10 production_notes; L11-15 other; L16-21 production_notes

**Doubts:**
- Three episodes are declared, but no individual episodes or scenes are supplied.
- The names in lines 12–15 occur only in casting notes; no people appear or speak in story content.

## F_glued_heading

_v2 with two SCENE 04 headings glued to the line before (the product's fault)_

**Verdict: GO** (expected go) · scored 9/9 · check findings left: 0 after one repair

| what | ok | detail |
|---|---|---|
| kind | yes | story_script |
| verdict | yes | go (expected go) |
| episodes | yes | 3 |
| scenes | yes | 13 of 13 |
| titles | yes | all match |
| headings clean | yes | only heading words |
| lengths | yes | all match |
| main people | yes | anudi, anudi's father, kasun |
| damaged text seen | yes | readable=False, 5 examples |

**Gates**

- `warn` gate 0 file: the text layer is damaged (line 25: Sinhala vowel signs appear before their consonants; copying the dialogue would preserve damaged text.; line 48: The Sinhala text has missing or displaced letter components.); read it from page images instead

| scene | heading (model's quote) | title | place | length | from the words |
|---|---|---|---|---|---|
| E01 S01 | SCENE 01 — KASUN'S EVERYDAY LIFE (L13) | KASUN'S EVERYDAY LIFE | Colombo roadside – Food three-wheeler | 27.6–27.6 s | Duration: 0.46 minutes |
| E01 S02 | SCENE 02 — ANUDI ARRIVES (L27) | ANUDI ARRIVES | Colombo road – Family car and roadside | 22.8–22.8 s | Duration: 0.38 minutes |
| E01 S03 | SCENE 03 — THE UNEXPECTED ENCOUNTER (L38) | THE UNEXPECTED ENCOUNTER | Colombo roadside – Near Kasun's food three-wheeler | 17.4–17.4 s | Duration: 0.29 minutes |
| E01 S04 | SCENE 04 — A CONVERSATION THAT CHANGES EVERYTHING (L51) | A CONVERSATION THAT CHANGES EVERYTHING | Colombo roadside – Near Kasun's food three-wheeler | 45–45 s | Duration: 0.75 minutes |
| E02 S01 | SCENE 01 — A FAMILIAR FACE (L83) | A FAMILIAR FACE | Kasun's food three-wheeler | 32.4–32.4 s | Duration: 0.54 minutes |
| E02 S02 | SCENE 02 — THE FATHER NOTICES (L103) | THE FATHER NOTICES | Colombo roadside | 22.8–22.8 s | Duration: 0.38 minutes |
| E02 S03 | SCENE 03 — THE CONFRONTATION (L114) | THE CONFRONTATION | Anudi's family home – Living room | 37.8–37.8 s | Duration: 0.63 minutes |
| E02 S04 | SCENE 04 — KASUN'S DETERMINATION AND THE BIG OPPORTUNITY (L137) | KASUN'S DETERMINATION AND THE BIG OPPORTUNITY | Kasun's small food preparation workspace | 60–60 s | Duration: 1 minute |
| E03 S01 | SCENE 01 — THE STRUGGLE (L181) | THE STRUGGLE | Kasun's workspace and Colombo – Different locations | 32.4–32.4 s | Duration: 0.54 minutes |
| E03 S02 | SCENE 02 — ANUDI'S SUPPORT (L197) | ANUDI'S SUPPORT | Anudi's family home – Bedroom | 22.8–22.8 s | Duration: 0.38 minutes |
| E03 S03 | SCENE 03 — AN UNEXPECTED OFFER (L213) | AN UNEXPECTED OFFER | Kasun's small workspace | 37.8–37.8 s | Duration: 0.63 minutes |
| E03 S04 | SCENE 04 — THE CHOICE (L236) | THE CHOICE | Same workspace | 32.4–32.4 s | Duration: 0.54 minutes |
| E03 S05 | SCENE 05 — A DREAM COMES TRUE (L255) | A DREAM COMES TRUE | KASUN'S Restaurant | 49.8–49.8 s | Duration: 0.83 minutes |

**People:** Kasun (main) aka කසුන්; Anudi (main) aka අනුදි; Anudi's father (main) aka Father, Her father, The father; Office worker aka customer; Office workers; Anudi's driver; Father's driver; Representative aka Representative (over the phone); Potential investor aka investor; Friends; Customers; Staff members

**Kind:** story_script (A three-episode drama presented as numbered scenes with locations, durations, action and attributed dialogue.)

**Text quality:** readable=False
- L25 `ෙරස්ටුරන්ට්`: Sinhala vowel signs appear before their consonants; copying the dialogue would preserve damaged text.
- L48 `ඔයාෙ ෙෆන්`: The Sinhala text has missing or displaced letter components.
- L205 `ෙකෙනක්ෙගන්වත්`: Multiple Sinhala vowel signs are displaced before consonants.
- L137 `daughter.SCENE 04`: The next scene heading is glued to the preceding scene's final sentence.
- L236 `father.SCENE 04`: The next scene heading is glued to the preceding scene's final sentence.

**Skipped:** L1-6 title_page; L7-10 production_notes; L12-12 production_notes; L79-79 end_marker; L81-82 production_notes; L177-177 end_marker; L179-180 production_notes; L287-287 end_marker; L288-299 production_notes

**Doubts:**
- Lines 137 and 236 each contain the preceding scene's final sentence and the next heading, so adjacent scene line ranges overlap at those lines.
- The drivers at lines 32 and 109 may be the same person, but the document does not establish this; they are listed separately.
- Narrated orders, thanks, conversations and telephone requests do not provide actual spoken wording; only lines containing supplied dialogue are marked as spoken_lines.
- The bank visit at line 186 implies an interlocutor but does not explicitly introduce an individual bank employee.
- Friends are mentioned as telephone contacts, but their individual appearances or audible replies are not specified.
- The late-night timing in episode 3 scene 1 applies explicitly to the document-review moment, not necessarily the whole multi-location sequence.
- Durations written as decimal minutes have been converted literally, not interpreted as minutes-and-seconds notation.
- Background groups are listed collectively because the document does not identify their individual members.

Lab spent $0.4318 of $2.00.
