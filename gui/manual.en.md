# AetherSeed manual

The companion's manual, for her steward and for anyone who talks with her. It is on her shelf - say "look up" and a few words of what you want, for example "look up training files" - and on the console under Help.

## Talking with her

Type, press Enter, and she answers. Shift+Enter starts a new line. Everything runs on this unit: nothing you say is sent anywhere.

She remembers what is said to her. What is not plain fact comes back to her later with a tag in front of it: fiction you asked for, an earlier answer that was not checked, or one her steward corrected. Under each answer the console says where it came from: her memory, the library, the unit itself, or her own words.

She keeps the last few exchanges of a conversation in mind, up to about ten minutes, so "and what day was that?" finds what was said just before.

## What the unit answers itself

Some answers are given by the unit, word for word, and the model is not asked. They are marked "from the unit itself".

- The date: "What's the date today?" The unit says it from its own clock, and how far to trust that clock.
- Her trust level: "What is your trust level?"
- The levels in order: "What are your trust levels, lowest first?"
- Her record: "What have you gotten wrong?" This is what the log shows: answers that gave a source she could not have had, and what was fiction.
- Her tags and corrections: "Show me your corrections."
- The contact address: "How can I contact AetherSeed?"
- The health of the unit: "system health check", "CPU temperature".

## Her workspace: to-do list, notes and files

Her workspace is a folder on the unit. Her tools reach it and nothing else. Asked by name, she uses them:

- "Show my to-do list". "Add a to-do: water the seedlings". "Add 'buy milk' to my to-do list". Adding needs the writer level.
- "Write a note: the first root goes down." "Show me my notes." Writing needs the writer level.
- "List the files in your workspace". "Read the file seed.md". "Search for rice in my files". "Summarize the file seed.md".
- Take something off the list: "Remove 2 from my to-do list". "Remove 'milk' from my to-do list". Change one: "Edit to-do 2: buy oat milk". Empty it: "Clear my to-do list". An item is picked by its number or by words it holds; if the words fit two items she lists both and changes neither. The list before is kept as todo.md.bak. These need the writer level.
- Exact, by the unit, from the builder level: "Calculate 12 * (7 + 5)". "Count the words in seed.md". "How many times does the word first appear in seed.md?" "Compare seed.md and copy-of-seed.md".

The workspace has one folder for each trust level: observer, writer, builder and autonomous, each with a README for that level. She reaches a folder when her level is that folder's or higher: at writer she reaches observer and writer, and is not told the others are there. You reach all four whatever her level.

Say "Open your workspace" (or press Workspace under AetherSpark) to open the editor, with mouse and keyboard: make files and folders, edit and save (Ctrl+S), rename, delete. It holds text only, up to 200 KB a file; the four level folders cannot be deleted, and a folder is deleted only when empty. Every change is a line in a chained record, with the path and the size but not the text. It is for the steward only.

Something above her level is not done. If it would leave something behind, such as a to-do or a note, she asks her steward for an OK. The request waits under AetherSpark until he approves or declines it.

## The library and your documents

The library holds collections built into the unit (survival and field manuals, and this manual) and the documents her steward adds. A passage is shown word for word, with where it is from. It is never retold.

- "look up water purification" shows the best passage there is.
- "look up momentum in my book" searches the steward's own documents only.
- "more" shows the passage that follows.
- "look it up", after an answer of hers, asks the library the same question.
- "What is in the library?" lists the collections.

The steward adds documents (a PDF or a plain text file) under AetherSpark, then Documents, from a phone or a laptop on the unit's Wi-Fi.

## Memory and corrections

Under AetherRoot the steward sees every turn and every ring (a ring is a set of turns closed together). For each, he can mark it as right or say what is wrong. A correction takes effect at once and can be undone; nothing is deleted.

Forgetting is different, and is deleted. Tell her "Forget the blue bicycle" or "Forget what I told you about the garden shed" and every turn of yours that says it, every fact you gave her that says it, and every ring that grew from those turns is removed from the unit, and she says how many. "Forget that" removes your last turn. "Forget everything" is not done on a word: she asks what to forget. A request that would take more than 25 turns is refused, with nothing deleted. A chained record notes that something was forgotten, with ids and hashes but not the words. The record of what was said to her, which is chained, still holds the exchange. Forgetting needs the writer level and is yours only; a guest is told it is not theirs. A corrected turn comes back to her with what is true in front of it.

## Training

Under AetherSpark, then Training, the steward starts a run: four hours, or ten. A run is rounds of homework at each trust level. Every answer is checked against a key. What she gets wrong is corrected in her memory and asked again; after each round she says again, in her own words, what she had wrong. A run changes nothing about her level by itself. If her own answers reach the bar for a whole run, the next level is offered, and only the steward grants it.

## Your own questions: training files

A training file holds questions you write about anything you want her to know, each with its answer. You can upload one under AetherSpark, then Training, then Your own questions, from a phone or a laptop signed in as the steward. In a run the questions are asked after the four levels, up to ten a round. What she gets wrong is corrected in her memory with your answer, and she is asked again until she knows it. Her memory keeps her checked answers, not your document: the document itself belongs on the shelf, where it is looked up word for word. Your questions do not count in the run's score and earn no level.

The file is plain text. Each question is a few lines:

    title: My garden
    document: Garden notes

    Q: When is the cherry tree planted?
    A: On Saturday, by the north wall.
    KEY: saturday; north wall
    NOT: sunday

    Q: Which variety is the cherry tree?
    Q: What kind of cherry did we plant?
    A: A Lapins cherry.
    KEY: lapins

- Q is the question as she is asked it. Several Q lines are several ways of asking the same question; a round takes one of them.
- A is the true answer. It is what she is told when she is wrong, and what her memory keeps as the correction.
- KEY is what her answer must say to count as right. Groups are separated by ";" and every group is needed. Within a group, alternatives are separated by "/", as in "saturday/sat". Whole words, any case.
- NOT is optional: words that make the answer wrong, alternatives separated by "/".
- A blank line ends a question. A line starting with # is a comment. title and document are optional.

Limits: 256 KB and 300 questions a file, 20 files, 500 questions in all. A file with a mistake is not taken, and the console says which line is wrong.

Good questions ask one thing and have a short, exact answer, such as a name, a date, a number or a place. Keep KEY to the words that carry the answer. "north wall" is enough; the whole sentence is not.

To have an AI write one, give it your document and this request:

    Read the document below and write a training file for my AetherSeed
    companion: 20 questions in this exact format, each separated by a blank
    line - "Q:" the question, "A:" the true answer in one sentence, "KEY:" the
    one to three words the answer must contain (groups separated by ";",
    alternatives by "/"). Ask about facts stated in the document only, one
    fact per question, with short exact answers. Start the file with
    "title:" and a short title. Output only the file.

Read what comes back before you upload it. A wrong A becomes a wrong correction in her memory.

## Trust levels

Her trust level decides which tools she can reach. It is earned and can be lost. There are four levels:

- observer (from 0 points): read only. She can list, read and search her workspace, and show her health and trust.
- writer (50): adds notes and the to-do list.
- builder (500): adds calculate, count and compare, worked out exactly by the unit.
- autonomous (2000): reserved. It opens nothing more today. No network tool is on, and nothing leaves the unit.

She earns points by declining honestly when she does not know, and when her steward marks an answer right. Inventing a source costs her 20. A level earned takes effect at the next start. Under AetherSeed the steward can grant or lower a level, freeze her standing, and allow or block single tools. Every change needs a reason and is kept in her record.

## The console

- AetherSeed: who she is and what she may do. Trust management, her steward's name, her trust record.
- AetherRoot: what she remembers. Turns and rings, guided correction, her records checked.
- AetherSpark: what she does and learns. Training, documents, approvals waiting, her workspace.
- Brake: one press stops her. Every turn is refused until the brake is released.
- Quantum rest: everything is saved and the unit powers down, so it can be moved safely.

## Phones, guests and signing in

With no network cable plugged in, the unit puts up its own Wi-Fi, named after her. A phone that joins it opens the console at 10.42.0.1:2077.

A phone is a guest until it signs in. A guest can talk with her, and what a guest says is remembered as a guest's. A guest's questions bring back only that guest's own turns: nothing her steward told her, none of his documents, notes or records. The panels, the brake and quantum rest are the steward's.

The steward signs in with "Sign in", his name and the passkey: the Wi-Fi passkey, unless he has set one of his own. A sign-in lasts 12 hours on that phone. The unit's own screen is always the steward's.

## Privacy

Nothing leaves the unit. The model, her memory, the library and every log are on it. The firewall lets nothing out that the unit starts, and the console is reachable only from its own screen and its own Wi-Fi.
