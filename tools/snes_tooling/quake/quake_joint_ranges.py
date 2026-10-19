"""Inclusive integer search domains, shared by capture preparation and fitting."""

DEPTH_Q16 = range(0, 1025)
MIDDLE_Y_Q1 = range(57, 390)
SOURCE_FOCALS = range(33, 65)
BACKGROUND_GAINS = (range(-1024, 1025), range(-512, 513),
                    range(-64, 65), range(-64, 65))


def require_focal_coverage(focals):
    """Every integer focal needs its own bound native images and arrival times."""
    if tuple(sorted(focals)) != tuple(SOURCE_FOCALS):
        raise ValueError(f'complete native focal coverage {SOURCE_FOCALS.start}–{SOURCE_FOCALS.stop-1} '
                         'at unit steps is required')


def inclusive_bounds(domain):
    return domain.start, domain.stop-1, domain.step
