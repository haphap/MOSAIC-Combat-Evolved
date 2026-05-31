# Package marker so the vendored data_collector tree ships in built artifacts.
# Upstream qlib runs this as a sys.path namespace dir; the collectors still add
# the parent (collectors/) to sys.path so ``from data_collector.base import ...``
# resolves the same way at run time.
