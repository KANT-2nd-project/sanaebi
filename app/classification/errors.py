"""Lightweight classifier failures shared by HTTP and routing policy code."""


class ClassificationUnavailable(Exception):
    """Files or metadata do not allow the classifier to be loaded."""


class ClassificationInferenceError(Exception):
    """A loaded classifier failed while predicting a label."""
