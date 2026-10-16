# Portable manifest fixtures

These gzip files contain the exact original snapshot and derived-view **manifest JSON only**.
`origin.json` binds their retained paths, uncompressed byte hashes and canonical content hashes.
Compression uses a fixed timestamp. They contain file inventories and existing manifest metadata;
no Parquet tables, Qlib bins, model files or prediction files are included.

The frozen study contract locks both content hashes. Replacing the manifests with smaller synthetic
manifests would change those identities. Unit tests therefore parse the original manifest bytes,
while replacing data-verification/execution ports with controlled fixtures as before. The real
source, receipt, calendar, budget and rejection checks remain exercised. No fixture grants data/PIT,
Workflow, Validation or research qualification. Historical artifacts remain in their original paths.

This removes the unit tests' dependency on `/home/zjw/...` and permits their existing offline checks
to run on an ordinary CI checkout. The separate retained-execution probe still requires its original
preparation and may skip when that historical evidence is unavailable.
