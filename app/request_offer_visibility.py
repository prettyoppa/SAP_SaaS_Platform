"""Who may see which RequestOffer rows in hub UI (consultants: own offers only)."""


def visible_request_offers_for_viewer(
    offers: list,
    *,
    viewer,
    owner_user_id: int,
    privileged_operator: bool = False,
) -> list:
    if getattr(viewer, "is_admin", False) or privileged_operator:
        return list(offers)
    if int(viewer.id) == int(owner_user_id):
        return list(offers)
    if getattr(viewer, "is_consultant", False):
        uid = int(viewer.id)
        return [o for o in offers if int(getattr(o, "consultant_user_id", 0) or 0) == uid]
    return []
