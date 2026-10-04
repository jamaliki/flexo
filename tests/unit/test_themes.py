

def test_a_theme_files_order_is_its_own_and_its_copy_looks_the_same() -> None:
    from flexo.colour import palette_colours
    from flexo.theme_files import register_theme
    from flexo.themes import palette_order, resolve_palette

    def strokes(theme: str, palette: object = None) -> list[str]:
        paint = resolve_palette(theme, palette)
        return [paint.get(f"tone-{index}-stroke") for index in range(1, 6)]

    stock = strokes("paper", "Deep Sea Harvest")
    # A theme file that writes the same colours in the palette's own order keeps that order...
    written = list(palette_colours("Deep Sea Harvest") or ())
    register_theme({"theme": {"name": "harvest-as-written", "base": "paper", "palette": written}})
    assert strokes("harvest-as-written") != stock
    # ...for itself alone: the stock palette on a deck is sorted for contrast as before.
    assert strokes("paper", "Deep Sea Harvest") == stock
    # A copy that writes them in the order the deck took them is the deck's colours exactly.
    register_theme({"theme": {"name": "harvest-copy", "base": "paper",
                              "palette": palette_order("paper", "Deep Sea Harvest")}})
    assert strokes("harvest-copy") == stock
