from html.parser import HTMLParser

import httpx

FORM_TAGS = {"input", "button", "form", "select", "textarea"}
NAV_TAGS = {"a"}
LANDMARK_TAGS = {"nav", "header", "footer"}
MAX_ELEMENTS = 60
# muchos sitios en produccion (WAF/anti-bot) rechazan el User-Agent default de httpx
# ("python-httpx/x.x") sin devolver ni un error claro — solo cortan la conexion.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}


class _FormElementExtractor(HTMLParser):
    """Prioriza inputs/botones/forms sobre links de navegacion.

    Una pagina con un menu grande (muchos <a>) puede pisar el presupuesto de elementos
    antes de llegar al formulario real si no se prioriza — los <a> solo llenan lo que sobra.
    """

    def __init__(self):
        super().__init__()
        self.form_elements: list[str] = []
        self.nav_elements: list[str] = []
        self._landmark_stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in LANDMARK_TAGS:
            self._landmark_stack.append(tag)

        if tag not in FORM_TAGS and tag not in NAV_TAGS:
            return
        attr_str = " ".join(f'{k}="{v}"' for k, v in attrs if k in ("id", "name", "type", "placeholder", "href"))
        element = f"<{tag} {attr_str}>".strip()
        if self._landmark_stack:
            # el mismo link suele repetirse en nav/header/footer (menu mobile oculto, sitemap);
            # este contexto le permite al LLM acotar el selector y no matchear el duplicado oculto.
            element = f"[{self._landmark_stack[-1]}] {element}"
        if tag in FORM_TAGS:
            self.form_elements.append(element)
        else:
            self.nav_elements.append(element)

    def handle_endtag(self, tag):
        if tag in LANDMARK_TAGS and tag in self._landmark_stack:
            self._landmark_stack.remove(tag)  # tolerante a HTML mal anidado en sitios reales

    @property
    def elements(self) -> list[str]:
        remaining = max(0, MAX_ELEMENTS - len(self.form_elements))
        return self.form_elements + self.nav_elements[:remaining]


def extract_elements(html: str) -> str | None:
    """Parsea HTML (crudo o ya renderizado por un browser) y devuelve el resumen de elementos.

    Compartido entre `inspect_page` (HTML crudo via httpx) y `authenticated_inspector`
    (HTML ya renderizado por Playwright, con JS ejecutado).
    """
    parser = _FormElementExtractor()
    parser.feed(html)
    if not parser.elements:
        return None
    return "\n".join(parser.elements)


def inspect_page(url: str) -> str | None:
    """Trae el HTML de la url y devuelve un resumen de los elementos de formulario/navegacion.

    ponytail: solo lee el HTML crudo (sin JS), sin autenticarse. Si la pagina es una SPA que
    renderiza el form con JavaScript, o esta detras de un login, esto no va a encontrar nada
    util — ahi hace falta un browser real logueado (ver `authenticated_inspector.py`). Se
    degrada devolviendo None.
    """
    try:
        response = httpx.get(url, timeout=10, follow_redirects=True, headers=REQUEST_HEADERS)
        response.raise_for_status()
    except httpx.HTTPError:
        return None

    return extract_elements(response.text)


def inspect_multiple(urls: list[str]) -> dict[str, str]:
    """Igual que `inspect_page` pero para varias URLs (paginas/pestañas mencionadas sin login).

    Una URL que falla o no tiene elementos simplemente se omite (no tumba las demas).
    """
    snapshots = {}
    for url in urls:
        elements = inspect_page(url)
        if elements:
            snapshots[url] = elements
    return snapshots


MAX_SNAPSHOT_CHARS = 4000


def format_snapshots(snapshots: dict[str, str]) -> str:
    """Junta los snapshots de varias paginas en un solo texto para el LLM.

    Cap duro de tamaño: con varias paginas (ej. 8 categorias de un e-commerce) el texto
    combinado puede pasar largo — probado en vivo, un caso real llego a >12.000 tokens en un
    solo request y exploto el limite por-minuto de un plan gratis de Groq. Mejor perder detalle
    de las ultimas paginas que fallar el request entero.
    """
    blocks = [f"== {url} ==\n{elements}" for url, elements in snapshots.items()]
    text = "\n\n".join(blocks)
    if len(text) > MAX_SNAPSHOT_CHARS:
        text = text[:MAX_SNAPSHOT_CHARS] + "\n... (truncado, habia mas elementos/paginas de los que entran aca)"
    return text
