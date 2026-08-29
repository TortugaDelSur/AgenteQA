from html.parser import HTMLParser

import httpx

INTERESTING_TAGS = {"input", "button", "a", "form", "select", "textarea"}
MAX_ELEMENTS = 40


class _FormElementExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in INTERESTING_TAGS or len(self.elements) >= MAX_ELEMENTS:
            return
        attr_str = " ".join(f'{k}="{v}"' for k, v in attrs if k in ("id", "name", "type", "placeholder", "href"))
        self.elements.append(f"<{tag} {attr_str}>".strip())


def inspect_page(url: str) -> str | None:
    """Trae el HTML de la url y devuelve un resumen de los elementos de formulario/navegacion.

    ponytail: solo lee el HTML crudo (sin JS). Si la pagina es una SPA que renderiza el form
    con JavaScript, esto no va a encontrar nada util — ahi hace falta un browser real
    (Playwright, que ya usa el runner de ejecucion de Persona B). Se degrada devolviendo None.
    """
    try:
        response = httpx.get(url, timeout=10, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    parser = _FormElementExtractor()
    parser.feed(response.text)

    if not parser.elements:
        return None

    return "\n".join(parser.elements)
