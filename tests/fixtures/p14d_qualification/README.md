# P14d qualification fixtures

Frozen synthetic offline fixtures for the clean-commit double-root P14d-B runner. They were
generated once using the repository's synthetic snapshot builder and official Qlib 0.9.7
`dump_bin.py` / `check_data_health.py`, then committed as immutable source input.

## SELECTED case

- Snapshot directory: `sha256-8dbde9cefc876820d4befa6eea384b3bbecd50fe0ffa471bed83ddb611b82db0`
- Snapshot content hash: `2f0e461c55a248d8e768d311bbcec20e997c64166d24dae926e959458f4e1ae2`
- View directory: `sha256-bde9ef5d66e1c7dc9b997a37e3ba6335813541d774a58b9655982320e1421cfe`
- View content hash: `cdb4f622989b5cc33a29fc5340410cee92a3c98383138bf3a7ec1a4e26b0788d`

## NO_SELECTION case

- Snapshot directory: `sha256-a37f8818479a203a3a2aa0ab5f03bf0cff4a2a9c1bc3f58eafb674ab880e110d`
- Snapshot content hash: `24857c3ffd7040b8708e1a265b67df705c12417b747cfae0d821ea9e2cef6954`
- View directory: `sha256-eb75938076ead9e4edf278b07a99f2a530cadbc2dd605be6441058c83fe0da01`
- View content hash: `43ffbc1a28ed6a0dda3fd13220fdbef629a37134118dd87a81f244afab216ae4`

The Qlib source/version binding is `0.9.7` at
`da920b7f954f48ab1bb64117c976710de198373e`. These fixtures are engineering inputs only:
they make no market-data, profitability, vendor-vintage PIT, Agent, or sealed-confirmation claim.
