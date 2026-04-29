"""Macro API URL compatibility module.

Legacy ``/api/macro/*`` endpoints were retired during the data-center cutover.
We keep an explicit empty router here so governance checks can verify the
standard interface layer shape without reintroducing retired routes.
"""

urlpatterns: list = []
