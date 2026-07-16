"""BoardRoom seeded-defect benchmark harness.

Proves Track 3's "measurable efficiency gain over single-agent baselines":
a fixed corpus of open-source KiCad boards, reproducible defect injection with
ground-truth manifests, and scoring of society vs. baseline reviews.

Runner-independent by design: everything here (corpus, seeding, metrics,
aggregation, charts) runs end-to-end against a deterministic mock reviewer
(`benchmark._execute.execute_review`) so the pipeline is testable today. The real
society/baseline runner is wired in at the single seam documented in
`benchmark/_execute.py`.
"""
