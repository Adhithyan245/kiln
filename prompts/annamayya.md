# Annamayya — C, Chemistry & Product

You're helping Annamayya build Kiln. Read `AGENTS.md` and `docs/interfaces.md` first. Only edit `src/kiln/agents/thermo.py`, `src/kiln/agents/kinetics.py`, `src/kiln/agents/precursor.py`, `src/kiln/tools/tammann.py`, `src/kiln/tools/precursors.py`, `src/kiln/review/`, `data/precursor_props.csv`, `app/` and their tests. Before each task, write a short plan and wait for my OK.

## Task 1 (Friday night): precursor table and Tammann helper
`kiln.tools.tammann.tammann_c(melting_point_c)` (two-thirds of the melting point in kelvin, returned in °C) with tests. `data/precursor_props.csv` contains `formula, decomposes_at_c, decomposition_product, decomposition_source, volatile_above_c, volatility_source, melting_point_c, melting_point_source, melting_point_source_url, melting_point_semantics, melting_point_semantics_source, melting_point_semantics_note`; every value needs a source, or is marked unknown. Preserve the Precursor Genome's published temperatures and citations. Set `melting_point_semantics` to `possible_decomposition_or_dehydration` only where the precursor's temperature could represent decomposition or dehydration in place of melting; otherwise use `as_reported`. This flag does not discard the value. Look up **one precursor's own properties** only, never whether two precursors react.
**Done when:** Tammann tests pass and all 46 Precursor Genome precursors are covered.

## Task 2 (Saturday morning): specialist logic and escalation rules
Thermo, Kinetics and Precursor agents per `docs/interfaces.md`. Each starts with the cheapest evidence and has a written **escalation rule** for when a costlier compute request is justified (for example, Thermo moves from `cached_lookup` to `bounded_relaxation` only when the driving force is within a set margin of the threshold). Every request carries a one-sentence `reason`; every claim has `falsified_if`.
**Done when:** with a stub compute client, the carbonate case on a development item produces the expected chain: decomposition found → `decomposition_reeval` → updated driving force → Kinetics re-check.

## Task 3 (Saturday afternoon): conflicts and review flags
`kiln.review.flags(item, accepted, requests)`: missing evidence, failed computation, specialist conflict, MLIP vs Materials Project disagreement above the protocol threshold, outside applicability. Plus the plain-language `disagreements` text for evidence cards. Then the chemistry sanity check with a mentor.
**Done when:** a test case for each flag reason raises exactly that flag.

## Task 4 (Saturday afternoon): evidence-card and review-queue UI
Rebuild the Kiln Triage prototype in `app/`, reading only `runs/` and `results/`: review queue (flagged pairs first), an evidence card per pair (prediction and applicability notes, calculations and settings, citations, specialist disagreements, compute requests with reason, cost and before/after, review flags), pair checker, and a results tab with coverage and compute allocation. Add a `Dockerfile` listening on `$PORT` for Cloud Run.
**Done when:** it runs on development outputs and deploys once to Cloud Run. On Sunday morning, load the final results and redeploy.
