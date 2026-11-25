"""Exact camera contacts used when unioning BSP visibility leaves."""
import numpy as np


def closed_leaf_contacts(points, nodes, planes, root):
    """Retain both exact plane ties, including point/line/coplanar contacts."""
    owners = np.arange(len(points), dtype=np.int64)
    current = np.full(len(points), root, dtype=np.int32)
    terminal_owners, terminals = [], []
    for _ in range(len(nodes) + 1):
        done = current < 0
        terminal_owners.extend(owners[done].tolist())
        terminals.extend((-current[done] - 1).tolist())
        owners, current = owners[~done], current[~done]
        if not len(current):
            return (np.asarray(terminal_owners, dtype=np.int64),
                    np.asarray(terminals, dtype=np.int32))
        if np.any(current >= len(nodes)):
            raise ValueError('mesh camera traversal escapes its nodes')
        selected = planes[nodes[current, 0]]
        distances = np.sum(points[owners] * selected[:, :3], axis=1) - selected[:, 3]
        children = nodes[current, 1:]
        following = children[np.arange(len(current)), (distances <= 0).astype(np.int32)]
        ties = np.flatnonzero((distances == 0) & (children[:, 0] != children[:, 1]))
        current = np.concatenate((following, children[ties, 0]))
        owners = np.concatenate((owners, owners[ties]))
    raise ValueError('closed mesh camera traversal did not terminate')
