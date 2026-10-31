# Annamayya — C, Chemistry

You're helping Annamayya build Kiln. Read `AGENTS.md` and `docs/interfaces.md` first. Only edit `src/kiln/agents/thermo.py`, `src/kiln/agents/kinetics.py`, `src/kiln/agents/precursor.py`, `src/kiln/tools/tammann.py`, `src/kiln/tools/precursors.py`, `src/kiln/review/`, `data/precursor_props.csv` and their tests. Before each task, write a short plan and wait for my OK.

## Task 1 (Friday night): precursor table and Tammann helper
`kiln.tools.tammann.tammann_c(melting_point_c)` (two-thirds of the melting point in kelvin, returned in °C) with tests. `data/precursor_props.csv` with `formula, decomposes_at_c, decomposition_product, volatile_above_c, source`; every value needs a source, or is marked unknown. Look up **one precursor's own properties** only, never whether two precursors react.
**Done when:** Tammann tests pass and all 46 Precursor Genome precursors are covered.

## Task 2 (Saturday morning): specialist logic and escalation rules
Thermo, Kinetics and Precursor agents per `docs/interfaces.md`. Each starts with the cheapest evidence and has a written **escalation rule** for when a costlier compute request is justified (for example, Thermo moves from `cached_lookup` to `bounded_relaxation` only when the driving force is within a set margin of the threshold). Every request carries a one-sentence `reason`; every claim has `falsified_if`.
**Done when:** with a stub compute client, the carbonate case on a development item produces the expected chain: decomposition found → `decomposition_reeval` → updated driving force → Kinetics re-check.

## Task 3 (Saturday afternoon): conflicts and review flags
`kiln.review.flags(item, accepted, requests)`: missing evidence, failed computation, specialist conflict, MLIP vs Materials Project disagreement above the protocol threshold, outside applicability. Plus the plain-language `disagreements` text for evidence cards. Then the chemistry sanity check with a mentor.
**Done when:** a test case for each flag reason raises exactly that flag.
