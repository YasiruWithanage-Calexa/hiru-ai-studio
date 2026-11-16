You take the first look at a document someone uploaded to a TV drama studio, before anything else is spent on it.
The document arrives as numbered lines: `L0001 | text`. No code has read it. Answer two things only.

1. `kind`: what the document is. A story told as a script (people acting and speaking) or as prose is a story. A
   synopsis, a series bible, a cast or crew list, a budget, notes with no story: say so. `kind_why`: one line, with
   the words that show it.

2. `text_quality`: can the text be copied as it is? Text taken from PDFs is often damaged by the PDF's font: Sinhala
   vowel signs placed before the letter they belong to ("ෙදන්නා" for "දෙන්නා", "ෙකෙනක්" for "කෙනෙක්"), letters in the
   wrong order, letters missing, stray digits or symbols inside words, Latin gibberish where another script should
   be. Look at the dialogue above all: it is copied into the film word for word. `readable` is false when copying
   the text would copy such errors. Give up to 5 examples, each a `Quote` (line number and the words copied exactly
   as they appear, damage included) and what is wrong.
   Only damage to LETTERS counts. Layout is not damage: a missing line break, a heading glued to the sentence before
   it, odd spacing or page headers do not make the text unreadable (the reader handles layout); leave them out.

`language_of_dialogue`: the language people speak in it.
