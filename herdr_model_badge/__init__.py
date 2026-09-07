"""Report each herdr agent's model and reasoning effort back to herdr as sidebar tokens."""

__version__ = "0.2.0"

#: Value of ``source`` on every ``pane.report_metadata`` call we make. herdr scopes
#: reported metadata per source, so this is what keeps our tokens ours.
SOURCE = "herdr-model-badge"
