# SPDX-License-Identifier: Apache-2.0
"""Thin adapters that hand HWPX/HWP ingest output to other Python frameworks.

Moved from python-hwpx ``hwpx.integrations`` (7.0 keeps the engine only):

* :mod:`hwpx_automation.integrations.langchain` -- ``HwpxLoader`` (``[langchain]`` extra)
* :mod:`hwpx_automation.integrations.llama_index` -- ``HwpxReader`` (``[llamaindex]`` extra)

Each adapter lives in its own submodule and imports its framework there, so
nothing here loads unless you import that submodule.
"""
