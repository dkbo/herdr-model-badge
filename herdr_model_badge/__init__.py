"""Report each herdr agent's model and reasoning effort back to herdr as sidebar tokens."""

__version__ = "0.4.0"

#: Value of ``source`` on the durable ``pane.report_metadata`` call we make. herdr
#: scopes reported metadata per source, so this is what keeps our tokens ours.
SOURCE = "herdr-model-badge"

#: Usage windows go out under a second source of their own. herdr expires a report
#: per source, so this is what lets the rate-limit rows lapse on a quiet pane while
#: the model beside them stays put.
USAGE_SOURCE = "herdr-model-badge-usage"
