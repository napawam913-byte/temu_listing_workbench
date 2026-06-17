from __future__ import annotations


def register_optional_image_plugins() -> None:
    """Register optional Pillow decoders when their packages are installed."""
    try:
        import pillow_avif  # noqa: F401
    except Exception:
        pass
