# Synthetic fixture benchmark seed

This directory contains only the deterministic source inputs for the synthetic
fixture benchmark: work orders, client profiles, the rubric, and empty judge
templates. Generated blind packets, routing data, scored judge passes, result
manifests, and public projections are deliberately not committed.

Generate a disposable benchmark workspace outside the repository:

```bash
python scripts/fixture_benchmark.py build /tmp/hwpx-fixture-benchmark
python scripts/fixture_benchmark.py validate /tmp/hwpx-fixture-benchmark
```

The generated data is synthetic qualification evidence only. It does not prove
human evaluation, real agent-client coverage, real Hancom verification, or a
human-replacement claim.
