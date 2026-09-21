"""Provider ordering — mirrors codenotch macOS ProviderOrder.swift."""


def arrange(providers, order, id_fn=lambda p: p.id):
    """Items in the remembered order, then anything new at the end."""
    order = list(order or ())
    if not order:
        return list(providers)
    by_id = {id_fn(p): p for p in providers}
    arranged = []
    for provider_id in order:
        provider = by_id.pop(provider_id, None)
        if provider is not None:
            arranged.append(provider)
    arranged.extend(by_id.values())
    return arranged


def joining_connected(provider_id, order, connected_ids):
    """Put a re-enabled provider after the ones already on screen."""
    rest = [pid for pid in order if pid != provider_id]
    connected = [pid for pid in rest if pid in connected_ids]
    if not connected:
        rest.insert(0, provider_id)
        return rest
    insert_at = max(rest.index(pid) for pid in connected) + 1
    rest.insert(insert_at, provider_id)
    return rest


def remember(visible_ids, remembered):
    """Keep hidden ids at the end so their place survives toggling off."""
    remembered = list(remembered or ())
    return list(visible_ids) + [pid for pid in remembered if pid not in visible_ids]
