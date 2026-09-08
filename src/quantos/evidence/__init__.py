"""Evidence package.

Entry points intentionally import concrete modules directly so the network-free
publisher process never loads the collector transport as an import side effect.
"""
