"""Personalization middleware primitives for nanobot."""

__all__ = ["PersonalizationGateway"]


def __getattr__(name: str):
    if name == "PersonalizationGateway":
        from nanobot.personalization.gateway import PersonalizationGateway

        return PersonalizationGateway
    raise AttributeError(name)
