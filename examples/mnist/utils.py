"""Small pure-Python preprocessing helpers compiled into the MNIST shortcut."""


def invert(values):
    """Invert normalized grayscale values (white↔black)."""
    return [1.0 - value for value in values]


def threshold(values, cutoff):
    """Binarize normalized values; intentionally written with list.append()."""
    result = []
    for value in values:
        if value >= cutoff:
            result.append(1.0)
        else:
            result.append(0.0)
    return result
