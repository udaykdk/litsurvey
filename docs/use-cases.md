# Use cases

Seven situations, with the commands to run, whether an LLM is involved, and
what leaves the machine. The confidentiality rules are explained in
[confidentiality.md](confidentiality.md).

Every scenario below assumes `litsurvey init` has been run once, or that you
accept the slower keyless operation. Replace the example topics with yours.

## 1. A student discovering a field

*Who:* a new master's or PhD student who has a topic and no reading list.
*LLM:* optional. *Leaves the machine:* keyword queries only.

```bash
# start broad, see what the field calls itself
litsurvey search "reconfigurable intelligent surface beamforming" -n 25 --abstracts

# take the most-cited hit and walk outwards
litsurvey cites "DOI:10.1109/TCOMM.2019.2929xxx" -n 20        # what built on it
litsurvey refs  "DOI:10.1109/TCOMM.2019.2929xxx" -n 20        # what it built on
litsurvey related "DOI:10.1109/TCOMM.2019.2929xxx"            # neighbours by content

# collect a reading list into a reference manager
litsurvey search "reconfigurable intelligent surface beamforming" -n 40 --out reading-list.bib

# read the free copies
litsurvey oa "10.1109/TCOMM.2019.2929xxx"
```

With an LLM backend, `litsurvey research "how is beamforming done with
reconfigurable intelligent surfaces, and what are the open problems"` writes
a first survey with numbered citations. Treat it as a map, not as a source:
open the cited papers.

## 2. Peer review without leaking the manuscript

*Who:* a reviewer for a journal or conference. *LLM:* yes, local backend
required. *Leaves the machine:* keyword queries only.

Read the manuscript yourself. For each contribution the paper claims as new,
state it as a generic topic and run:

```bash
litsurvey doctor        # last line must say backend=ollama (local)
litsurvey novelty "adaptive sampling of collocation points in physics-informed neural networks using residual gradients" --out claim1.md
```

The report ends with a verdict (clearly novel / incremental advance /
substantially anticipated / cannot determine) and a search log. For the
closest prior work it cites, look yourself:

```bash
litsurvey cites "DOI:10.xxxx/closest-paper" --abstracts
litsurvey oa "10.xxxx/closest-paper"
```

Do not paste any sentence, table or figure caption from the manuscript
anywhere. See [confidentiality.md](confidentiality.md).

## 3. Checking your own literature survey before submission

*Who:* an author about to submit. *LLM:* optional. *Leaves the machine:*
keyword queries, and your own claim phrasing if you use `novelty`.

The goal is to find the papers a referee will say you missed.

```bash
# several phrasings of the same idea, including older terminology
litsurvey search "inverse design metasurface deep learning" --year-from 2021 -n 30 --out sweep1.csv
litsurvey search "metasurface neural network surrogate optimisation" --year-from 2021 -n 30 --out sweep2.csv
litsurvey search "data-driven electromagnetic structure design" -n 30 --out sweep3.csv

# for each paper you already cite that is central, check who cited it recently
litsurvey cites "DOI:10.xxxx/your-key-reference" -n 30 --year-from 2023

# the recommender finds work that uses vocabulary you did not search for
litsurvey related "DOI:10.xxxx/your-key-reference"
```

Merge the CSV files in a spreadsheet and mark what is already in your
bibliography. With a backend, `litsurvey novelty "<your main contribution>"
--out check.md` gives you the referee's view before the referee does; your
claim text goes to the backend, so use a local one if the work is
unpublished.

## 4. The state-of-the-art section of a thesis or proposal

*Who:* a PhD student writing chapter 2, or an investigator writing a
proposal. *LLM:* recommended. *Leaves the machine:* keyword queries; the
question text goes to the backend.

```bash
litsurvey research "methods for uncertainty quantification in physics-informed neural networks" --rounds 12 --out uq-survey.md
```

The report is organised by theme with numbered citations, an "open problems"
section and a "coverage caveats" section. Then build the bibliography from
the papers it found:

```bash
litsurvey history                       # find the run id of the research run
litsurvey search "uncertainty quantification physics-informed neural networks" -n 40 --out chapter2.bib
```

Read the papers. The survey tells you where to look; it is not a substitute
for reading.

## 5. Seeding a systematic review

*Who:* a team doing a systematic review or mapping study. *LLM:* no.
*Leaves the machine:* keyword queries only.

PRISMA-style reporting requires the databases, exact search strings, dates
and hit counts. litsurvey records all of these.

```bash
litsurvey search "digital twin structural health monitoring" --sources openalex,s2,arxiv -n 100 --out screen-A.csv
litsurvey search "digital twin bridge monitoring" -n 100 --out screen-B.csv
litsurvey history                       # every run has a date and hit counts per source
```

Each run's JSON in `~/.litsurvey/runs/` holds the per-source hit counts
(`stats`). The CSV files feed your screening spreadsheet. Note the caps: the
APIs return at most 100 results per query, so split broad topics into
several specific queries.

## 6. Finding reviewers, or an editor

*Who:* an editor, programme committee chair, or an author asked to suggest
reviewers. *LLM:* no. *Leaves the machine:* a paper ID only.

```bash
litsurvey cites "DOI:10.xxxx/the-submission-s-key-reference" -n 30
litsurvey related "DOI:10.xxxx/the-submission-s-key-reference" -n 30 --out candidates.csv
```

The author lists of the results are the people working closest to the topic.

## 7. Watching what builds on your own paper

*Who:* any author. *LLM:* no. *Leaves the machine:* your paper's DOI.

```bash
litsurvey cites "DOI:10.1109/TAP.2024.3463805" -n 50 --out citing.csv
```

Run it every few months; compare the CSV files.

## What every scenario has in common

- Start with two or three different phrasings; the indexes match words, not
  meaning. `related` is the way to escape your own vocabulary.
- The `id:` field printed with every result is the handle for `cites`,
  `refs`, `related`, `paper` and `oa`.
- `--out file.bib` on any list command gives a reference-manager import.
- Everything is recorded; `litsurvey history` or the web page's History tab
  brings a run back, with the same downloads.
