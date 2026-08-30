from html.parser import HTMLParser

import httpx

FORM_TAGS = {"input", "button", "form", "select", "textarea"}
NAV_TAGS = {"a"}
MAX_ELEMENTS = 60


class _FormElementExtractor(HTMLParser):
    """Prioriza inputs/botones/forms sobre links de navegacion.

    Una pagina con un menu grande (muchos <a>) puede pisar el presupuesto de elementos
    antes de llegar al formulario real si no se prioriza — los <a> solo llenan lo que sobra.
    """

    def __init__(self):
        super().__init__()
        self.form_elements: list[str] = []
        self.nav_elements: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in FORM_TAGS and tag not in NAV_TAGS:
            return
        attr_str = " ".join(f'{k}="{v}"' for k, v in attrs if k in ("id", "name", "type", "placeholder", "href"))
        element = f"<{tag} {attr_str}>".strip()
        if tag in FORM_TAGS:
            self.form_elements.append(element)
        else:
            self.nav_elements.append(element)

    @property
    def elements(self) -> list[str]:
        remaining = max(0, MAX_ELEMENTS - len(self.form_elements))
        return self.form_elements + self.nav_elements[:remaining]


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
