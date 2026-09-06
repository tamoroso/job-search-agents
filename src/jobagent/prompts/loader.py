import re, hashlib, yaml
from functools import cache
from pathlib import Path
from jinja2 import Environment, StrictUndefined, meta
from jobagent.prompts.base import Prompt

class PromptError(Exception):
    """Prompts record register errors"""

class PromptNotFound(PromptError):
    def __init__(self, agent: str, version: str, path : Path):
        self.agent, self.version, self.path = agent, version, path
        super().__init__(f"prompt not found: {agent}/{version} ({path})")

class PromptLoadError(PromptError):
    def __init__(self, path: Path, reason: str):
        self.path, self.reason = path, reason
        super().__init__(f"{path}: {reason}")

PROMPTS_DIR = Path(__file__).parent
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
VERSION_RE = re.compile(r"\Av(\d+)\Z")

_env = Environment(undefined=StrictUndefined, autoescape=False,
                   keep_trailing_newline=True)


def _parse(path: Path) -> Prompt:
    agent, stem = path.parent.name, path.stem
    if not (m := VERSION_RE.match(stem)):
        raise PromptLoadError(path, "invalid_version_name")

    match = FRONTMATTER.match(path.read_text(encoding="utf-8"))
    if not match:
        raise PromptLoadError(path, "malformed_or_no_frontmatter")
    meta_raw, body = match.groups()
    fm = yaml.safe_load(meta_raw)

    if fm["agent"] != agent or fm["version"] != stem:
        raise PromptLoadError(path, "inconsistent_frontmatter_vs_path")

    declared = frozenset(fm["variables"])
    used = meta.find_undeclared_variables(_env.parse(body))
    if declared != used:
        raise PromptLoadError(path,
            f"variables_error | declared : {sorted(declared)} | used : {sorted(used)}")

    return Prompt(
        agent=agent, version=stem,
        hash=hashlib.sha256(body.encode()).hexdigest()[:12],
        body=body, variables=declared,
        output_schema=fm["output_schema"],
        model_tier=fm["model_tier"],
    )


@cache
def registry() -> dict[str, Prompt]:
    prompts = {}
    for path in sorted(PROMPTS_DIR.glob("*/v*.md")):
        p = _parse(path)
        if p.key in prompts:
            raise PromptLoadError(f"clé dupliquée: {p.key}")
        prompts[p.key] = p
    if not prompts:
        raise PromptNotFound(f"aucun prompt trouvé sous {PROMPTS_DIR}")
    return prompts


def get(agent: str, version: str) -> Prompt:
    key = f"{agent}/{version}"
    try:
        return registry()[key]
    except KeyError:
        raise PromptLoadError("cache_storage", f"cannot_retrieve_cached_prompt : {key}") from None