"""Building the dictionary files the app ships, from pinned sources.

- `entry_ids`: stable entry IDs and the registry that carries them across
  dictionary updates (decision 0007).
- `sources`: each source pinned to a version and checksum; fetching them.
- `cedict`, `ecdict`: reading CC-CEDICT's text and ECDICT's CSV.
- `wordfreq_ranks`: frequency ranks from wordfreq's data.
- `kaikki`, `jmdict`: reading Wiktionary as kaikki.org extracts it, and
  JMdict as jmdict-simplified's JSON.
- `spanish`: Spanish's own rules - pronominal verbs and attached pronouns.
- `russian`: Russian's own rules - stress marks, ё, which listed forms are
  inflections, participles declined.
- `packs`: `python -m tools.dictionaries.packs` writes the basic packs
  (Spanish, Russian, Japanese), not shipped yet (decision 0035).
- `coverage`: the probe a basic pack must pass - the share of its
  language's FLEURS sentences' words it finds (`probe/`) - and the share
  of running words it finds, by wordfreq's frequencies.
- `build`: `python -m tools.dictionaries.build` writes the dictionary files
  and their credits (decision 0009).
- `update_ids`: run when a source's pinned version changes, to carry entry
  IDs from the old release to the new one.
"""
