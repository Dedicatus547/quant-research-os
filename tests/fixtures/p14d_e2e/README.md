# P14d offline E2E Qlib fixture

This fixture removes the integration test's dependency on the ignored developer workspace
directory `.tools/qlib-0.9.7`.

- Snapshot: `sha256-df8bcbaca23b87d92f31dcbbfe8a4bd4b96efff7f55ce5f21e2b917883e04045`
- Snapshot content hash: `86fe0e0e57c16a914118f15c82c70d956313362f5257fba0d35b0d8d1fcc4399`
- Qlib view: `sha256-927b4a3b4dfc7030f295fbe5b71c89e2558d30bf913c3a16b116c99470a366e1`
- Qlib view content hash: `499eb72e7365edc4e77a38af7b9ecf6f6a7accbbc589ec730c03e05b44382741`
- Qlib view source snapshot: `df8bcbaca23b87d92f31dcbbfe8a4bd4b96efff7f55ce5f21e2b917883e04045`
- Qlib version/source binding: `0.9.7` / `da920b7f954f48ab1bb64117c976710de198373e`

The snapshot is a deterministic synthetic offline fixture. The view was produced once by the
official Qlib 0.9.7 `dump_bin.py` and `check_data_health.py` tools. The fixture is frozen source
input for tests and qualification; it is never a market-data claim.
